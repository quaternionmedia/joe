"""A take opened while a question is still being asked, and answers given over it.

The capture tests script the stream (no audio device): a quiet room, then a
question's echo, then whatever the person does. A scripted watch closes at a
known block, as an unwatch or the listen after the question would close it.
"""

import json
import sys
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api
from Modules.Control import Answered, Control
from Modules.Conversation import Conversation
from Modules.Voice import NoMicrophoneError
from Modules.Watch import Unwatched, Watch, barge_factor, barge_in_by_voice
from tests.test_voice import _blk, _blocks_kept, _fake_stream_sd

ROOM, LOUD = 0.0005, 0.2
ECHO = (0.02, 0.03, 0.015, 0.025)  # a question said through a speaker, as the microphone hears it


def _echo(n):
    return [_blk(ECHO[i % len(ECHO)]) for i in range(n)]


class _Watch(Watch):
    """A watch closed at its `close_at`th check: the take checks once a block."""

    def __init__(self, close_at=None, **kwargs):
        kwargs.setdefault("voice", True)
        kwargs.setdefault("factor", 2.0)
        kwargs.setdefault("learn_seconds", 1.5)
        super().__init__(**kwargs)
        self.checks, self.close_at = 0, close_at

    def closed(self):
        self.checks += 1
        if self.close_at is not None and self.checks >= self.close_at:
            self.close()
        return super().closed()


class _Held(Control):
    """A real control whose talk key is held from one block to another."""

    def __init__(self, watch, held_from, held_until):
        super().__init__()
        self.watch, self.held_from, self.held_until = watch, held_from, held_until

    @property
    def held(self):
        return self.held_from <= self.watch.checks < self.held_until


def _capture(blocks, watch, control=None, **kwargs):
    from Modules.Voice import _capture_until_silence

    kwargs.setdefault("max_duration", 5.0)
    kwargs.setdefault("silence_after", 0.3)
    fake_sd, _ = _fake_stream_sd(blocks)
    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        return _capture_until_silence(device=None, control=control, watch=watch, **kwargs)


# --- the control --------------------------------------------------------------


def test_a_question_is_interrupted_by_an_answer_a_held_key_or_speech_over_it():
    """Mutation: leave speech over the question out of `interrupted` -- red."""
    control = Control()
    assert control.snapshot()["interrupted"] is False

    control.speech_began()
    assert control.snapshot()["interrupted"] is True
    control.quiet()
    assert control.snapshot()["interrupted"] is False

    control.hold(True)
    assert control.snapshot()["interrupted"] is True
    control.hold(False)
    control.answer("hold")
    assert control.snapshot()["interrupted"] is True


def test_the_switches_read_the_environment(monkeypatch):
    monkeypatch.delenv("JOE_BARGE_IN", raising=False)
    assert barge_in_by_voice() is True
    monkeypatch.setenv("JOE_BARGE_IN", "0")
    assert barge_in_by_voice() is False
    for value, factor in (("3", 3.0), ("0.5", 1.0), ("loud", 2.0)):
        monkeypatch.setenv("JOE_BARGE_FACTOR", value)
        assert barge_factor() == factor


def test_a_watch_the_listen_closed_cannot_begin_after_it():
    """The listen asks and closes in one step. Mutation: ask without closing
    -- red, a take could begin after the listen recorded afresh."""
    unbegun = Watch(voice=True)
    assert unbegun.adopt() is False
    assert unbegun.began() is False and not unbegun.begun.is_set()

    begun = Watch(voice=True)
    assert begun.began() is True and begun.adopt() is True


# --- the take -----------------------------------------------------------------


def test_speech_louder_than_the_echo_begins_it_from_its_onset():
    """The take keeps the onset and nothing of the question before it.
    Mutation: keep the blocks before the onset -- red, the question's echo
    would be transcribed with the answer."""
    control = Control()
    watch = _Watch(control=control)
    blocks = [_blk(ROOM)] * 2 + _echo(26) + [_blk(LOUD)] * 6 + [_blk(ROOM)] * 10

    samples, _, speech = _capture(blocks, watch, control=control)

    assert speech is True and watch.begun.is_set()
    # one block of echo before the onset, the six loud ones, three quiet to end
    assert _blocks_kept(samples) == 10
    assert control.snapshot()["interrupted"] is True


def test_the_echo_alone_never_begins_it_even_after_a_pause():
    """After a pause the room's floor has fallen; the echo's remembered level
    has not. Mutation: judge against the room alone -- red, the question's
    next word begins the take."""
    watch = _Watch(close_at=58)
    blocks = [_blk(ROOM)] * 2 + _echo(30) + [_blk(ROOM)] * 15 + _echo(10) + [_blk(ROOM)] * 3

    with pytest.raises(Unwatched):
        _capture(blocks, watch)

    assert not watch.begun.is_set()


def test_nothing_begins_while_the_echo_is_learned():
    """A question's opening can rise block on block, each more than twice the
    last, which the echo's level alone would take for a person. Mutation:
    let speech begin while learning -- red."""
    watch = _Watch(close_at=20)
    blocks = [_blk(ROOM)] * 2 + [_blk(level) for level in (0.01, 0.03, 0.09, 0.27)] + _echo(15)

    with pytest.raises(Unwatched):
        _capture(blocks, watch)

    assert not watch.begun.is_set()


@pytest.mark.parametrize(("factor", "begins"), [(2.0, True), (4.0, False)])
def test_the_margin_over_the_echo_is_the_watch_s(factor, begins):
    """0.07 is a little over twice the echo's loudest block. Mutation: ignore
    the factor -- red on the second row."""
    watch = _Watch(close_at=None if begins else 46, factor=factor)
    blocks = [_blk(ROOM)] * 2 + _echo(20) + [_blk(ROOM)] * 15 + [_blk(0.07)] * 6 + [_blk(ROOM)] * 6

    if begins:
        _, _, speech = _capture(blocks, watch)
        assert speech is True and watch.begun.is_set()
    else:
        with pytest.raises(Unwatched):
            _capture(blocks, watch)
        assert not watch.begun.is_set()


def test_a_voice_rising_into_its_first_word_still_begins_it():
    """An answer about twice the question's loudness, rising over three
    blocks, begins the take: the echo's level is learned in its window and
    then held, not tracked. Mutation: keep learning the echo after its
    window -- red."""
    watch = _Watch()
    blocks = ([_blk(ROOM)] * 2 + _echo(20) + [_blk(level) for level in (0.04, 0.07, 0.12, 0.12, 0.12)]
              + [_blk(ROOM)] * 6)

    _, _, speech = _capture(blocks, watch)

    assert speech is True and watch.begun.is_set()


def test_a_held_key_begins_it_whatever_the_level():
    """Held while the echo is still being learned, released seven blocks
    later. Mutation: let a hold not begin the watch -- red."""
    watch = _Watch()
    control = _Held(watch, held_from=5, held_until=12)
    blocks = [_blk(ROOM)] * 2 + _echo(10) + [_blk(ROOM)] * 20

    samples, _, speech = _capture(blocks, watch, control=control)

    assert speech is True and watch.begun.is_set()
    assert _blocks_kept(samples) == 9  # two before the key, and the seven held


def test_an_answer_by_key_is_left_for_the_take_that_replaces_the_watch():
    """Mutation: take answers while watching -- red, `Answered` is raised by a
    take nobody will read."""
    control = Control()
    control.answer("approve")
    watch = _Watch(close_at=6, control=control)

    with pytest.raises(Unwatched):
        _capture([_blk(ROOM)] * 2 + _echo(5), watch, control=control)

    assert control.take_answer() == "approve"


def test_the_watch_counts_toward_no_cap_and_the_take_s_cap_counts_from_its_onset():
    """Mutation: count the watched blocks toward the cap -- red, the take
    ends inside the question with nothing heard."""
    watch = _Watch()
    blocks = [_blk(ROOM)] * 2 + _echo(20) + [_blk(ROOM)] * 15 + [_blk(LOUD)] * 12 + [_blk(ROOM)] * 5

    samples, _, speech = _capture(blocks, watch, max_duration=0.5)

    assert speech is True and _blocks_kept(samples) == 8  # the onset's three, then the cap's five


def test_joe_barge_in_0_leaves_only_the_keys(monkeypatch):
    """Mutation: ignore the switch -- red."""
    monkeypatch.setenv("JOE_BARGE_IN", "0")
    watch = _Watch(close_at=40, voice=None)
    blocks = [_blk(ROOM)] * 2 + _echo(26) + [_blk(LOUD)] * 6 + [_blk(ROOM)] * 10

    with pytest.raises(Unwatched):
        _capture(blocks, watch)

    assert watch.voice is False and not watch.begun.is_set()


def test_closing_a_begun_take_ends_it():
    """Mutation: check for closing only before the take begins -- red, an
    unwatched take runs on to its pause."""
    watch = _Watch(close_at=32)
    blocks = [_blk(ROOM)] * 2 + _echo(26) + [_blk(LOUD)] * 12 + [_blk(ROOM)] * 10

    with pytest.raises(Unwatched):
        _capture(blocks, watch)

    assert watch.begun.is_set()


# --- the routes ---------------------------------------------------------------


@pytest.fixture
def fresh(monkeypatch):
    control, conversation = Control(), Conversation()
    monkeypatch.setattr(api, "control", control)
    monkeypatch.setattr(api, "conversation", conversation)
    monkeypatch.setattr(api, "watching", None)
    return control, conversation


class _Voice:
    """`Voice` with its listens scripted: each a function of the watch it was given."""

    script: list = []
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    def transcribe_samples(self, samples, hint=None, prompt=None):
        return {"text": "", "segments": [], "info": {}}

    def listen(self, **kwargs):
        _Voice.calls.append(kwargs)
        return _Voice.script.pop(0)(kwargs)


@pytest.fixture
def voice(monkeypatch):
    _Voice.script, _Voice.calls = [], []
    monkeypatch.setattr(api, "Voice", _Voice)
    return _Voice


def _until_closed(kwargs):
    deadline = time.monotonic() + 3
    while not kwargs["watch"].closed() and time.monotonic() < deadline:
        time.sleep(0.01)
    raise Unwatched()


def _spoken_over(text):
    def listen(kwargs):
        kwargs["on_event"]("listening")
        kwargs["watch"].began()
        kwargs["on_event"]("hearing")
        return {"text": text, "source": "voice", "take": "t-over", "audio_path": "a.wav"}
    return listen


def test_a_take_begun_over_the_question_is_the_listen_s(fresh, voice):
    """Mutation: never adopt a watch -- red, the answer said over the question
    is dropped and the listen records afresh."""
    control, conversation = fresh
    voice.script = [_spoken_over("approve")]
    client = TestClient(api.app)

    assert client.post("/api/voice/watch", params={"duration": 4, "hint": "approve, hold"}).json() == {
        "watching": True, "voice": True}
    api.watching.finished.wait(2)
    assert client.get("/api/voice/control").json()["interrupted"] is True

    heard = client.post("/api/voice/listen", params={"duration": 4}).json()

    assert heard["text"] == "approve" and len(voice.calls) == 1
    assert voice.calls[0]["hint"] == "approve, hold" and voice.calls[0]["watch"] is not None
    assert control.snapshot()["interrupted"] is False  # the take that interrupted is over
    states = [e["state"] for e in conversation.snapshot()["events"]]
    assert "hearing" in states and "listening" not in states  # nothing published before it began
    take = [json.loads(line) for line in (api.datapoints.root / "segments.jsonl").read_text().splitlines()][-1]
    assert take["kind"] == "take" and take["over_question"] is True


def test_a_watch_nobody_began_is_closed_and_the_listen_records_afresh(fresh, voice):
    voice.script = [_until_closed, lambda kwargs: {"text": "hold", "audio_path": "b.wav"}]
    client = TestClient(api.app)

    client.post("/api/voice/watch", params={"duration": 4})
    heard = client.post("/api/voice/listen", params={"duration": 4}).json()

    assert heard["text"] == "hold" and len(voice.calls) == 2
    assert voice.calls[1]["watch"] is None and api.watching is None


def test_unwatch_closes_it_and_a_new_watch_closes_the_last(fresh, voice):
    voice.script = [_until_closed, _until_closed, _until_closed]
    client = TestClient(api.app)

    client.post("/api/voice/watch")
    first = api.watching
    assert client.post("/api/voice/unwatch").json() == {"watching": False}
    assert first.closed() and first.finished.is_set() and api.watching is None

    client.post("/api/voice/watch")
    second = api.watching
    client.post("/api/voice/watch")
    assert second.closed() and second.finished.is_set() and api.watching is not second
    client.post("/api/voice/unwatch")


def test_a_watch_refuses_what_a_listen_refuses(fresh, voice):
    client = TestClient(api.app)

    for params in ({"duration": 0}, {"duration": 61}, {"silence_ms": 50}, {"hint": "x" * 501}):
        assert client.post("/api/voice/watch", params=params).status_code == 400
    assert api.watching is None


def test_a_microphone_that_fails_under_a_begun_watch_fails_the_listen(fresh, voice):
    def fails(kwargs):
        kwargs["watch"].began()
        raise NoMicrophoneError("no audio")

    voice.script = [fails]
    client = TestClient(api.app)

    client.post("/api/voice/watch")
    api.watching.finished.wait(2)

    assert client.post("/api/voice/listen").status_code == 503


def test_no_turn_cue_plays_when_the_answer_is_already_waiting_by_key(fresh, monkeypatch):
    """Mutation: drop the waiting check -- red, a tone plays for a turn already over."""
    control, conversation = fresh
    played = []
    monkeypatch.setattr(api.Cue, "play", lambda kind, settle=False: played.append(kind) or True)
    conversation.publish("speaking", text="Approve or hold?")
    control.answer("approve")
    with patch("api.Voice") as fake:
        fake.return_value.listen.return_value = {"text": "approve", "source": "key"}
        api.voice_listen(duration=4.0)

    assert played == ["heard"]
