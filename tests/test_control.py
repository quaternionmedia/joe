"""An answer by key or button, a held key, and the cues that let the turn be followed by ear.

The capture tests script the stream (no audio device) and a control whose
state changes at known blocks: the take consults it once per block.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api
from Modules import Cue
from Modules.Control import Answered, Control
from Modules.Conversation import Conversation
from tests.test_voice import _blk, _blocks_kept, _fake_stream_sd

QUIET, LOUD = 0.0005, 0.2


class _Scripted:
    """A control held from block `held_from` until `held_until`, answering at `answer_at`."""

    def __init__(self, held_from=None, held_until=None, answer_at=None):
        self.block = 0
        self.held_from, self.held_until, self.answer_at = held_from, held_until, answer_at

    def take_answer(self):
        self.block += 1
        return "approve" if self.block == self.answer_at else None

    @property
    def held(self):
        return self.held_from is not None and self.held_from <= self.block < self.held_until


def _capture(blocks, control, **kwargs):
    from Modules.Voice import _capture_until_silence

    fake_sd, _ = _fake_stream_sd(blocks)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        return _capture_until_silence(device=None, control=control, **kwargs)


# --- the control --------------------------------------------------------------


def test_an_answer_is_taken_once_and_lapses_when_nobody_takes_it():
    now = [0.0]
    control = Control(clock=lambda: now[0], answer_seconds=15.0)

    control.answer("hold")
    assert control.snapshot()["answer_waiting"] is True
    assert control.take_answer() == "hold"
    assert control.take_answer() is None

    control.answer("approve")
    now[0] = 16.0
    assert control.snapshot()["answer_waiting"] is False
    assert control.take_answer() is None  # Mutation: drop the lapse -- red.


def test_a_hold_is_a_flag_the_take_reads():
    control = Control()
    control.hold(True)
    assert control.held and control.snapshot()["held"] is True
    control.hold(False)
    assert not control.held


# --- the take -----------------------------------------------------------------


def test_an_answer_given_during_a_take_ends_it_at_once():
    """Mutation: drop the answer check from the block loop -- red, the take
    runs on to the speaker's pause."""
    with pytest.raises(Answered) as given:
        _capture([_blk(QUIET)] * 3 + [_blk(LOUD)] * 20, _Scripted(answer_at=4),
                 max_duration=5.0, silence_after=0.3)

    assert given.value.text == "approve"


def test_a_held_key_keeps_the_turn_open_through_a_pause_and_its_release_ends_it():
    """Unheld, the pause ends this take after three quiet blocks. Mutation:
    let a pause end a held take -- red."""
    blocks = [_blk(QUIET)] * 3 + [_blk(LOUD)] * 3 + [_blk(QUIET)] * 12 + [_blk(LOUD)] * 3 + [_blk(QUIET)] * 20

    samples, _, speech = _capture(blocks, _Scripted(held_from=1, held_until=24),
                                  max_duration=5.0, silence_after=0.3)

    assert speech is True
    assert _blocks_kept(samples) == 23  # blocks 1..23 read; the release at 24 ends it


def test_a_held_key_carries_the_take_past_its_cap():
    """Mutation: keep `max_duration` as the bound while held -- red."""
    samples, _, _ = _capture([_blk(LOUD)] * 40, _Scripted(held_from=1, held_until=31),
                             max_duration=1.0, silence_after=0.3)

    assert _blocks_kept(samples) == 30


def test_a_release_with_nothing_loud_still_counts_as_speech():
    """The person said they were speaking by holding the key."""
    _, _, speech = _capture([_blk(QUIET)] * 20, _Scripted(held_from=1, held_until=6),
                            max_duration=5.0, silence_after=0.3)

    assert speech is True


def test_an_answer_waiting_before_the_take_is_returned_without_opening_the_microphone(tmp_path):
    from Modules.Voice import Voice

    control = Control()
    control.answer("hold")
    seen = []
    fake_sd = MagicMock()
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        result = Voice(capture_dir=str(tmp_path)).listen(
            duration=5.0, until_silence=True, control=control,
            on_event=lambda state, **d: seen.append((state, d.get("source"))))

    assert result["text"] == "hold" and result["source"] == "key" and result["speech_detected"] is True
    fake_sd.InputStream.assert_not_called()
    assert seen == [("heard", "key")]


# --- the routes ---------------------------------------------------------------


@pytest.fixture
def fresh(monkeypatch):
    control, conversation = Control(), Conversation()
    monkeypatch.setattr(api, "control", control)
    monkeypatch.setattr(api, "conversation", conversation)
    return control, conversation


def test_the_answer_route_takes_a_word_and_refuses_anything_else(fresh):
    client = TestClient(api.app)

    assert client.post("/api/voice/answer", json={"text": " approve "}).json()["answer_waiting"] is True
    assert fresh[0].take_answer() == "approve"
    for bad in ({"text": ""}, {"text": "x" * 101}, {"text": 3}, ["approve"]):
        assert client.post("/api/voice/answer", json=bad).status_code == 400
    assert client.post("/api/voice/answer", content=b"not json").status_code == 400


def test_the_hold_route_sets_and_clears_the_hold(fresh):
    client = TestClient(api.app)

    assert client.post("/api/voice/hold", json={"held": True}).json()["held"] is True
    assert client.get("/api/voice/control").json()["held"] is True
    assert client.post("/api/voice/hold", json={"held": False}).json()["held"] is False
    assert client.post("/api/voice/hold", json={"held": "yes"}).status_code == 400


def test_a_question_s_options_reach_the_stream_and_are_refused_anywhere_else(fresh):
    client = TestClient(api.app)

    event = client.post("/api/voice/conversation", json={
        "state": "speaking", "text": "Say approve or hold.", "options": ["approve", "hold"]}).json()
    assert event["options"] == ["approve", "hold"]
    for bad in ({"state": "recorded", "text": "approve", "options": ["approve"]},
                {"state": "speaking", "options": [str(i) for i in range(10)]},
                {"state": "speaking", "options": ["approve", ""]},
                {"state": "speaking", "options": "approve"}):
        assert client.post("/api/voice/conversation", json=bad).status_code == 400


# --- the cues -----------------------------------------------------------------


def _listen_with(state, monkeypatch, result=None):
    played = []
    monkeypatch.setattr(api.Cue, "play", lambda kind, settle=False: played.append(kind) or True)
    api.conversation.publish(state, text="Say approve or hold.")
    with patch("api.Voice") as voice:
        voice.return_value.listen.return_value = result or {"text": "approve"}
        api.voice_listen(duration=4.0)
    return played


def test_the_turn_cue_plays_before_a_listen_that_answers_a_question(fresh, monkeypatch):
    """Mutation: drop the state check -- red, the silent wait chirps."""
    assert _listen_with("speaking", monkeypatch) == ["turn"]


def test_no_cue_plays_before_the_next_take_of_a_silent_wait(fresh, monkeypatch):
    assert _listen_with("no_speech", monkeypatch) == []


def test_the_heard_cue_plays_for_an_answer_by_key_and_when_a_take_is_read(fresh, monkeypatch):
    assert _listen_with("no_speech", monkeypatch, {"text": "hold", "source": "key"}) == ["heard"]
    played = []
    monkeypatch.setattr(api.Cue, "play", lambda kind, settle=False: played.append(kind) or True)
    api._report("transcribing")
    assert played == ["heard"]


def test_cues_play_through_the_output_and_joe_cues_0_silences_them(monkeypatch):
    fake_sd = MagicMock()
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        assert Cue.play("heard") is False  # the suite's own JOE_CUES=0
        monkeypatch.setenv("JOE_CUES", "1")
        assert Cue.play("turn") is True

    samples, rate = fake_sd.play.call_args.args
    assert rate == Cue.RATE and 0 < float(abs(samples).max()) <= Cue.VOLUME + 1e-6  # float32
    fake_sd.wait.assert_called_once()


def test_a_cue_that_cannot_play_costs_the_turn_nothing(monkeypatch):
    monkeypatch.setenv("JOE_CUES", "1")
    fake_sd = MagicMock()
    fake_sd.play.side_effect = OSError("no output device")
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        assert Cue.play("turn") is False
