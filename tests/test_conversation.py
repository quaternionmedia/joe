"""The conversation's live states: the bus, the routes, and what the endpointer reports.

No audio device is touched: the stream is the scripted one `test_voice.py`
feeds the endpointer through its callback.
"""

import asyncio
import json
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api
from Modules.Conversation import POSTED, STATES, Conversation
from tests.test_voice import _blk, _fake_stream_sd


@pytest.fixture
def conversation(monkeypatch):
    fresh = Conversation()
    monkeypatch.setattr(api, "conversation", fresh)
    return fresh


@pytest.fixture
def client():
    return TestClient(api.app)


# --- the bus ------------------------------------------------------------------


def test_events_are_numbered_in_order_and_read_back_after_a_number():
    c = Conversation()
    first = c.publish("speaking", text="Voice check. Say approve or hold.")
    c.publish("listening")
    c.publish("hearing")

    assert [e["state"] for e in c.since(first["seq"])] == ["listening", "hearing"]
    assert c.snapshot()["state"] == "hearing"


def test_an_unknown_state_is_refused():
    with pytest.raises(ValueError):
        Conversation().publish("thinking")


def test_the_level_is_kept_apart_from_the_events():
    """Ten levels a second would push every state change out of the backlog."""
    c = Conversation(keep=3)
    c.publish("listening")
    for _ in range(20):
        c.level(0.01, 0.003)

    assert [e["state"] for e in c.snapshot()["events"]] == ["listening"]
    assert c.current_level()["seq"] == 20


def test_nothing_published_reads_as_idle():
    assert Conversation().snapshot()["state"] == "idle"


# --- the routes ---------------------------------------------------------------


@pytest.mark.parametrize("state", POSTED)
def test_the_dialog_posts_its_own_states(client, conversation, state):
    response = client.post("/api/voice/conversation", json={"state": state, "text": "x"})

    assert response.status_code == 200, response.text
    assert conversation.snapshot()["state"] == state


@pytest.mark.parametrize("state", sorted(set(STATES) - set(POSTED)))
def test_a_post_cannot_claim_a_state_the_microphone_reports(client, conversation, state):
    response = client.post("/api/voice/conversation", json={"state": state})

    assert response.status_code == 400
    assert "microphone" in response.json()["detail"]
    assert conversation.snapshot()["events"] == []


def test_a_reask_carries_its_reason(client, conversation):
    client.post("/api/voice/conversation",
                json={"state": "speaking", "text": "I heard: banana. Say approve or hold.",
                      "reason": "nomatch"})

    assert conversation.snapshot()["events"][-1]["reason"] == "nomatch"


def test_a_body_that_is_not_json_is_refused(client, conversation):
    response = client.post("/api/voice/conversation", content=b"speaking",
                           headers={"content-type": "application/json"})
    assert response.status_code == 400


def test_the_state_route_returns_the_snapshot(client, conversation):
    conversation.publish("listening")
    body = client.get("/api/voice/conversation/state").json()

    assert body["state"] == "listening"
    assert body["events"][0]["state"] == "listening"


class _Request:
    """A request that disconnects after `polls` checks."""

    def __init__(self, polls: int, last_event_id: str | None = None):
        self.polls = polls
        self.headers = {"last-event-id": last_event_id} if last_event_id else {}

    async def is_disconnected(self) -> bool:
        self.polls -= 1
        return self.polls < 0


def _drain(request) -> list[str]:
    async def collect():
        return [chunk async for chunk in api._conversation_events(request, poll=0)]
    return asyncio.run(collect())


def test_the_stream_replays_the_backlog_then_the_level(conversation):
    conversation.publish("speaking", text="Voice check.")
    conversation.publish("listening")
    conversation.level(0.02, 0.004)

    chunks = _drain(_Request(polls=1))
    events = [json.loads(c.split("data: ", 1)[1]) for c in chunks if c.startswith("id: ")]
    levels = [c for c in chunks if c.startswith("event: level")]

    assert [e["state"] for e in events] == ["speaking", "listening"]
    assert len(levels) == 1 and '"rms": 0.02' in levels[0]


def test_the_stream_resumes_after_the_last_event_the_client_saw(conversation):
    first = conversation.publish("speaking")
    conversation.publish("listening")

    chunks = _drain(_Request(polls=1, last_event_id=str(first["seq"])))
    states = [json.loads(c.split("data: ", 1)[1])["state"] for c in chunks if c.startswith("id: ")]

    assert states == ["listening"]


# --- what the microphone reports ----------------------------------------------


def _states(blocks, **kwargs) -> list[str]:
    from Modules.Voice import _capture_until_silence

    seen: list[str] = []
    fake_sd, _ = _fake_stream_sd(blocks)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        _capture_until_silence(max_duration=10.0, device=None, silence_after=0.3,
                               on_event=lambda state, **detail: seen.append(state), **kwargs)
    return seen


def test_the_endpointer_reports_the_protocol_not_the_block_rate():
    quiet, loud = 0.0005, 0.2
    blocks = ([_blk(quiet)] * 3 + [_blk(loud)] * 4 + [_blk(quiet)] * 2
              + [_blk(loud)] * 3 + [_blk(quiet)] * 20)

    seen = _states(blocks)
    phases = [s for s in seen if s != "level"]

    # Speech, a short pause, speech again, then the pause that ends the turn.
    assert phases == ["listening", "hearing", "pausing", "hearing", "pausing"]
    # And one level per block the take kept: 3 + 4 + 2 + 3 + 3.
    assert seen.count("level") == 15


def test_a_click_is_not_reported_as_hearing():
    quiet, loud = 0.0005, 0.2
    blocks = [_blk(quiet)] * 3 + [_blk(loud)] + [_blk(quiet)] * 200

    phases = [s for s in _states(blocks) if s != "level"]

    assert phases == ["listening"]


def test_a_watcher_that_raises_does_not_cost_the_take():
    from Modules.Voice import _capture_until_silence

    def broken(state, **detail):
        raise RuntimeError("the panel fell over")

    fake_sd, _ = _fake_stream_sd([_blk(0.0005)] * 3 + [_blk(0.2)] * 4 + [_blk(0.0005)] * 20)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        samples, _, speech = _capture_until_silence(
            max_duration=10.0, device=None, silence_after=0.3, on_event=broken)

    assert speech is True and samples.size > 0


def test_listen_reports_no_speech_without_reading(tmp_path, monkeypatch):
    import numpy as np

    import Modules.Voice as voice_module

    monkeypatch.setattr(voice_module, "_capture_until_silence",
                        lambda **kw: (np.zeros(1600, dtype="float32"), None, False))
    monkeypatch.setattr(voice_module, "resolve_input_device", lambda d: 0)
    transcribe = []
    monkeypatch.setattr(voice_module.Voice, "transcribe", lambda self, p: transcribe.append(p))

    seen = []
    voice_module.Voice(capture_dir=str(tmp_path)).listen(
        until_silence=True, on_event=lambda s, **d: seen.append(s))

    assert seen == ["no_speech"] and transcribe == []


def test_listen_reports_reading_then_what_was_heard(tmp_path, monkeypatch):
    import numpy as np

    import Modules.Voice as voice_module

    monkeypatch.setattr(voice_module, "_capture_until_silence",
                        lambda **kw: (np.zeros(1600, dtype="float32"), None, True))
    monkeypatch.setattr(voice_module, "resolve_input_device", lambda d: 0)
    monkeypatch.setattr(voice_module.Voice, "transcribe", lambda self, p: {"text": "approve"})

    seen = []
    voice_module.Voice(capture_dir=str(tmp_path)).listen(
        until_silence=True, on_event=lambda s, **d: seen.append((s, d.get("text"))))

    assert seen == [("transcribing", None), ("heard", "approve")]


def test_the_listen_route_publishes_what_the_microphone_reports(client, conversation, monkeypatch):
    class FakeVoice:
        def listen(self, **kwargs):
            kwargs["on_event"]("listening")
            kwargs["on_event"]("level", rms=0.02, threshold=0.004)
            kwargs["on_event"]("hearing")
            kwargs["on_event"]("heard", text="hold")
            return {"text": "hold", "audio_path": "a.wav", "speech_detected": True}

    monkeypatch.setattr(api, "Voice", FakeVoice)

    assert client.post("/api/voice/listen").status_code == 200
    snapshot = conversation.snapshot()
    assert [e["state"] for e in snapshot["events"]] == ["listening", "hearing", "heard"]
    assert snapshot["level"]["rms"] == 0.02
