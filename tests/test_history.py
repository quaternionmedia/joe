"""The whole transcript, read back from the datapoints and served for the page."""

import json

import pytest
from fastapi.testclient import TestClient

import api
from Modules import History
from Modules.Transcript import Datapoints


def _write(data, *records):
    for kind, fields in records:
        data.write(kind, **fields)


def test_the_transcript_holds_both_sides_in_order_with_strikes_labels_and_outcomes(tmp_path):
    """Mutation: drop the said entries -- red; ignore the strikes -- red."""
    data = Datapoints(root=tmp_path, enabled=True)
    _write(data,
           ("said", {"text": "What should be done?"}),
           ("segment", {"take": "t1", "index": 1, "text": "to the pi", "start_s": 1.2, "end_s": 1.9}),
           ("segment", {"take": "t1", "index": 0, "text": "deploy vox", "start_s": 0.1, "end_s": 0.8}),
           ("take", {"take": "t1", "text": "deploy to the pi", "source": "voice", "confidence": 0.5,
                     "audio": "capture_1.wav", "struck": {"0": [1]}}),
           ("outcome", {"take": "t1", "state": "recorded", "text": "deploy to the pi"}),
           ("label", {"take": "t1", "label": "misheard", "by": "t2"}),
           ("said", {"text": "Agree or again?", "reason": "confirm"}))

    entries = History.read(data.manifest)

    assert [e["kind"] for e in entries] == ["said", "take", "said"]
    take = entries[1]
    assert [s["words"] for s in take["segments"]] == [["deploy", "vox"], ["to", "the", "pi"]]
    assert take["segments"][0]["struck"] == [1] and take["segments"][1]["struck"] == []
    assert take["segments"][0]["start"] == 0.1 and take["confidence"] == 0.5
    assert take["label"] == "misheard" and take["outcome"] == "recorded"
    assert entries[2] == {**entries[2], "text": "Agree or again?", "reason": "confirm"}


def test_a_take_that_never_ended_is_no_entry_and_a_cut_line_is_skipped(tmp_path):
    data = Datapoints(root=tmp_path, enabled=True)
    _write(data, ("segment", {"take": "closed", "index": 0, "text": "run in qmcp"}))
    with data.manifest.open("a", encoding="utf-8") as out:
        out.write('{"kind": "take", "take": "half\n')
    _write(data, ("take", {"take": "t2", "text": "approve", "source": "key"}))

    entries = History.read(data.manifest)

    assert [e["take"] for e in entries] == ["t2"] and entries[0]["segments"] == []


def test_the_last_entries_are_kept_and_nothing_written_is_nothing_read(tmp_path):
    data = Datapoints(root=tmp_path, enabled=True)
    for i in range(5):
        _write(data, ("said", {"text": f"line {i}"}))

    assert [e["text"] for e in History.read(data.manifest, limit=2)] == ["line 3", "line 4"]
    assert History.read(tmp_path / "missing.jsonl") == []


def test_a_sentence_said_is_written_from_the_conversation_route(monkeypatch):
    """Mutation: write no said datapoint -- red, the transcript holds one side."""
    from Modules.Conversation import Conversation

    monkeypatch.setattr(api, "conversation", Conversation())
    client = TestClient(api.app)

    client.post("/api/voice/conversation", json={"state": "speaking", "text": "Approve or hold?",
                                                  "reason": "repeat", "options": ["approve", "hold"]})
    client.post("/api/voice/conversation", json={"state": "idle", "text": "done"})

    records = [json.loads(line) for line in api.datapoints.manifest.read_text().splitlines()]
    said = [r for r in records if r["kind"] == "said"]
    assert len(said) == 1 and said[0]["text"] == "Approve or hold?"
    assert said[0]["reason"] == "repeat" and said[0]["options"] == ["approve", "hold"]


def test_the_history_route_serves_the_transcript_within_its_bounds():
    """Mutation: serve no entries -- red."""
    api.datapoints.write("said", text="Ready. What should be done?")
    client = TestClient(api.app)

    served = client.get("/api/voice/history").json()
    assert served["kept"] is True and served["entries"][-1]["text"] == "Ready. What should be done?"
    for bad in (0, 2001):
        assert client.get("/api/voice/history", params={"limit": bad}).status_code == 400
