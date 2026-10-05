"""joe's own spoken words: declared once, acted on inside the take, served for the page.

A segment saying one of joe's phrases is struck -- it was said to joe -- and
acted on: "start over" strikes the take so far, "flag that" and "that was right"
label the take before, and "how loud am I" shows the voice's level as a note.
"""

import itertools
import json

from fastapi.testclient import TestClient

import api
from Modules import Vocabulary
from Modules.Transcript import Datapoints, LiveTranscript, plain
from tests.test_transcript import _Heard, _samples

STATS = {"peak_rms": 0.06, "mean_rms": 0.02, "threshold": 0.01, "noise_floor": 0.003}


def _live(*texts, tmp_path=None, previous=None):
    notes = []
    data = Datapoints(root=tmp_path, enabled=True) if tmp_path else None
    live = LiveTranscript(_Heard(*texts), datapoints=data, previous=previous,
                          notify=lambda state, **d: notes.append((state, d)))
    for i, _ in enumerate(texts):
        live.add(_samples(), i * 1.0, i * 1.0 + 0.5, STATS)
    return live, notes


# --- what is declared ----------------------------------------------------------------


def test_every_entry_says_what_it_does_is_written_as_heard_and_means_one_thing():
    shown = Vocabulary.entries()
    assert {e["key"] for e in shown} >= {"take.scratch", "take.start_over", "label.misheard",
                                         "label.heard_right", "diagnostic.level"}
    for item in shown:
        assert item["says"], item["key"]
        for phrase in item["phrases"]:
            assert phrase == plain(phrase), (item["key"], phrase)
    for first, second in itertools.combinations(shown, 2):
        assert not set(first["phrases"]) & set(second["phrases"]), (first["key"], second["key"])


def test_the_vocabulary_is_served_for_the_page():
    """Mutation: serve nothing -- red."""
    served = TestClient(api.app).get("/api/voice/vocabulary").json()

    assert served == {"phrases": Vocabulary.entries()}


# --- acted on inside the take ------------------------------------------------------


def test_start_over_strikes_everything_said_so_far():
    """Mutation: drop the start-over rule -- red, the abandoned words stay."""
    live, _ = _live("deploy vox to the", "start over", "deploy qmcp")

    assert live.finish() == "deploy qmcp"


def test_a_label_marks_the_take_before_and_strikes_itself(tmp_path):
    """Mutation: write no label -- red; label this take rather than the one
    before -- red."""
    live, notes = _live("Flag that.", tmp_path=tmp_path, previous="take-before")

    assert live.finish() == ""
    records = [json.loads(line) for line in (tmp_path / "segments.jsonl").read_text().splitlines()]
    labels = [r for r in records if r["kind"] == "label"]
    assert labels == [{**labels[0], "take": "take-before", "label": "misheard", "by": live.take}]
    assert notes == [("note", {"text": "The last take is marked misheard.", "label": "misheard",
                               "of": "take-before"})]


def test_that_was_right_marks_it_heard_right_and_nothing_to_mark_says_so(tmp_path):
    live, notes = _live("That was right.", tmp_path=tmp_path, previous="t0")
    live.finish()
    assert notes[0][1]["label"] == "heard right"

    alone, notes = _live("flag that")
    alone.finish()
    assert notes == [("note", {"text": "No take to mark yet.", "label": "misheard"})]


def test_how_loud_am_i_shows_the_peak_against_the_threshold():
    """Mutation: drop the level rule -- red, the words go on to the question."""
    live, notes = _live("How loud am I?")

    assert live.finish() == ""
    state, note = notes[0]
    assert state == "note" and note["level"] == 6.0
    assert note["text"] == "The voice peaked at 6.0 times the threshold: clear."


def test_a_note_reaches_the_conversation_stream(monkeypatch):
    """The route hands the transcript a way to tell the page. Mutation: build
    it without `notify` -- red, nothing is published."""
    from Modules.Conversation import Conversation

    conversation = Conversation()
    monkeypatch.setattr(api, "conversation", conversation)
    built = {}
    real = api.LiveTranscript

    def capture(*args, **kwargs):
        built.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "LiveTranscript", capture)
    monkeypatch.setattr(api, "last_take", "the-take-before")

    class FakeVoice:
        def transcribe_samples(self, samples, hint=None, prompt=None):
            return {"text": ""}

        def listen(self, **kwargs):
            return {"text": ""}

    monkeypatch.setattr(api, "Voice", FakeVoice)
    api.voice_listen(duration=2.0)
    built["notify"]("note", text="The last take is marked misheard.")

    assert built["previous"] == "the-take-before"
    assert conversation.snapshot()["events"][-1]["state"] == "note"
