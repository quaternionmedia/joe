"""The `/family` routes: joe as a member of the performing family, on `family/1`.

The hub delivers joe its part of a cue's family block, a take. Most of these
hold the routes to their answers with the pipeline stood in for, so they are
quick and say exactly what was asked of it. The last runs the real API under
uvicorn and the real pipeline, as `joe serve` does, and reads the result back
through the page's own route. `test_family_conformance.py` replays the
contract's own cases.
"""

import asyncio
import io
import json
import os
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import soundfile
from fastapi.testclient import TestClient

import api
from Modules import Family

REPO = Path(__file__).resolve().parent.parent
CUE = {"number": "3", "name": "Second tune", "fired_at": "2026-10-10T20:00:00+00:00"}
TAKE = {"take": {"notes": ["C4", "E4", "G4", "C5"], "seconds_per_note": 0.5}}


def notes(*events_per_note: int) -> list[dict]:
    """A transform's MIDI notes, each heard `n` times."""
    return [{"note": "C4", "pitch": 60,
             "start_dur": [{"start_time": i, "duration": 0.5} for i in range(n)]}
            for n in events_per_note]


# Seven events: three notes heard twice in Raw and one heard once in Harmonic.
# Not the number of notes (four) nor of transforms (two).
FOUND = {"Raw": {"midi": {"notes": notes(2, 2, 2)}}, "Harmonic": {"midi": {"notes": notes(1)}}}
EVENTS = 7


class Pipeline:
    """Stands in for main.py: records each recording it is given and writes a
    Process_Data for it holding FOUND, unless told to fail. Holds each run until
    `release` is set, so a test can see a take still running."""

    def __init__(self, output: Path, status: int = 0):
        self.output, self.status = output, status
        self.ran: list[Path] = []
        self.release = threading.Event()
        self.release.set()

    def __call__(self, path: Path) -> int:
        self.release.wait(timeout=10)
        self.ran.append(path)
        if self.status != 0:
            return self.status
        run = self.output / f"run{len(self.ran)}"
        run.mkdir(parents=True)
        data = {"audio": {path.stem: {"chroma": FOUND}}}
        (run / f"Process_Data_{len(self.ran)}.json").write_text(json.dumps(data), encoding="utf-8")
        return 0


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    stand_in = Pipeline(tmp_path / "Output")
    member = Family.Member(audio_dir=tmp_path / "Audio", output_dir=tmp_path / "Output", run=stand_in)
    monkeypatch.setattr(api, "family", member)
    return stand_in


@pytest.fixture
def client(pipeline):
    return TestClient(api.app)


def settled(client, timeout: float = 10.0) -> dict:
    """`/family/state` once no take is running."""
    deadline = time.monotonic() + timeout
    while True:
        body = client.get("/family/state").json()
        if not body["state"]["busy"]:
            return body
        assert time.monotonic() < deadline, f"still busy after {timeout} s: {body}"
        time.sleep(0.02)


# ─── GET /family/state ────────────────────────────────────────────────────────

def test_state_before_any_cue_names_joe_and_nothing_else(client):
    res = client.get("/family/state")
    assert res.status_code == 200
    assert res.json() == {"member": "joe", "cue": None,
                          "state": {"latest": None, "busy": False, "error": None}}


# ─── POST /family/cue: a take ─────────────────────────────────────────────────

def test_a_take_is_accepted_at_once_and_reported_when_the_pipeline_is_done(client, pipeline):
    pipeline.release.clear()

    res = client.post("/family/cue", json={"cue": CUE, "action": TAKE})

    assert res.status_code == 202
    assert res.json() == {"ok": True, "state": {"latest": None, "busy": True, "error": None},
                          "instance": api.family.instance}
    running = client.get("/family/state").json()
    assert running["cue"] == CUE and running["state"]["busy"] is True
    pipeline.release.set()

    done = settled(client)
    (recording,) = pipeline.ran
    assert recording.name.startswith("cue-3_") and recording.suffix == ".wav"
    assert done == {"member": "joe", "cue": CUE,
                    "state": {"latest": {"file": recording.name, "events": EVENTS},
                              "busy": False, "error": None}}


def test_the_recording_is_the_notes_asked_for(client, pipeline):
    client.post("/family/cue", json={"cue": CUE, "action": {"take": {
        "notes": ["C4", "A4"], "seconds_per_note": 0.4}}})
    settled(client)

    (recording,) = pipeline.ran
    signal, rate = soundfile.read(io.BytesIO(recording.read_bytes()))
    assert len(signal) == 2 * int(0.4 * rate)
    for index, hertz in enumerate((261.63, 440.0)):
        note = signal[index * int(0.4 * rate):(index + 1) * int(0.4 * rate)]
        spectrum = np.abs(np.fft.rfft(note))
        loudest = np.fft.rfftfreq(len(note), 1 / rate)[spectrum.argmax()]
        assert abs(loudest - hertz) < 5, (index, loudest)


def test_seconds_per_note_defaults_to_half_a_second(client, pipeline):
    client.post("/family/cue", json={"cue": CUE, "action": {"take": {"notes": ["C4"]}}})
    settled(client)

    signal, rate = soundfile.read(io.BytesIO(pipeline.ran[0].read_bytes()))
    assert len(signal) == int(0.5 * rate)


def test_takes_run_in_turn_and_the_latest_is_the_last(client, pipeline):
    second = {**CUE, "number": "4", "name": "Third tune"}
    pipeline.release.clear()
    client.post("/family/cue", json={"cue": CUE, "action": TAKE})
    client.post("/family/cue", json={"cue": second, "action": TAKE})
    assert client.get("/family/state").json()["cue"] == second
    pipeline.release.set()

    done = settled(client)
    assert [p.name.split("_")[0] for p in pipeline.ran] == ["cue-3", "cue-4"]
    assert done["state"]["latest"]["file"] == pipeline.ran[1].name


def test_a_pipeline_that_fails_is_reported_and_keeps_the_last_good_take(client, pipeline):
    client.post("/family/cue", json={"cue": CUE, "action": TAKE})
    good = settled(client)["state"]["latest"]
    pipeline.status = 1

    client.post("/family/cue", json={"cue": {**CUE, "number": "4"}, "action": TAKE})
    state = settled(client)["state"]

    assert state["latest"] == good
    assert state["error"].startswith("RuntimeError: the pipeline exited 1 on cue-4_")


def test_the_pipeline_is_main_py_on_that_one_file_from_the_checkout(monkeypatch, tmp_path):
    """As `POST /api/run/{filename}` runs it, by the recording's name: with no
    name, main.py would take the newest file in Data/Audio/, whoever made it."""
    calls = []
    monkeypatch.setattr(api.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs))
                        or subprocess.CompletedProcess(argv, 0))
    recording = tmp_path / "cue-3_x.wav"

    assert api._run_pipeline(recording) == 0

    ((argv, kwargs),) = calls
    assert argv == [sys.executable, str(api._MAIN_PY), "cue-3_x.wav"]
    assert kwargs["cwd"] == str(api._PROJECT_ROOT)
    assert api.family.output_dir == api._PROJECT_ROOT / "Data" / "Output"


# ─── POST /family/cue: refused, never 500 ─────────────────────────────────────

NOT_UNDERSTOOD = [
    pytest.param({"cue": CUE, "action": {"clock": "start"}}, id="another-member-s-action"),
    pytest.param({"cue": CUE, "action": {"patch": "simple"}}, id="carlos-s-action"),
    pytest.param({"cue": CUE, "action": {**TAKE, "clock": "start"}}, id="a-take-and-more"),
    pytest.param({"cue": CUE, "action": {}}, id="no-action"),
    pytest.param({"cue": CUE}, id="action-missing"),
    pytest.param({"cue": CUE, "action": "take"}, id="action-not-an-object"),
    pytest.param({"cue": CUE, "action": {"take": ["C4"]}}, id="take-not-an-object"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": []}}}, id="no-notes"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": "C4"}}}, id="notes-not-a-list"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"] * 17}}}, id="too-many-notes"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["H4"]}}}, id="not-a-note"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": [60]}}}, id="a-number-not-a-name"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["G#9"]}}}, id="beyond-midi"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"], "seconds_per_note": 0}}},
                 id="no-seconds"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"], "seconds_per_note": 60}}},
                 id="too-many-seconds"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"], "seconds_per_note": "0.5"}}},
                 id="seconds-as-text"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"], "seconds_per_note": True}}},
                 id="seconds-as-a-boolean"),
    pytest.param({"cue": CUE, "action": {"take": {"notes": ["C4"], "bpm": 120}}},
                 id="a-key-joe-does-not-know"),
    pytest.param({"cue": "3", "action": TAKE}, id="cue-not-an-object"),
    pytest.param({"action": TAKE}, id="cue-missing"),
    pytest.param([{"cue": CUE, "action": TAKE}], id="body-a-list"),
]


@pytest.mark.parametrize("body", NOT_UNDERSTOOD)
def test_what_joe_does_not_understand_is_422_and_changes_nothing(client, pipeline, body):
    res = client.post("/family/cue", json=body)

    assert res.status_code == 422
    assert res.json()["ok"] is False
    assert isinstance(res.json()["error"], str) and res.json()["error"]
    assert client.get("/family/state").json() == {
        "member": "joe", "cue": None, "state": {"latest": None, "busy": False, "error": None}}
    assert pipeline.ran == []


@pytest.mark.parametrize("raw", [b"", b"{", b"take C4", b"\xff\xfe"], ids=["empty", "cut", "text", "bytes"])
def test_a_body_that_is_not_json_is_422_not_500(client, raw):
    res = client.post("/family/cue", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert res.json()["ok"] is False


def test_an_unknown_action_says_what_joe_understands(client):
    res = client.post("/family/cue", json={"cue": CUE, "action": {"clock": "start"}})
    assert res.json() == {"ok": False,
                          "error": "joe understands one action, {\"take\": {...}}; got ['clock']"}


def test_a_cue_joe_fails_taking_is_500_in_the_contract_s_shape_and_changes_nothing(
        client, monkeypatch):
    """The take cannot be started: understood, and joe failed acting on it."""
    class NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    # Only where the member makes its worker: the test client has threads of its own.
    monkeypatch.setattr(Family, "threading", types.SimpleNamespace(Thread=NoThread))
    monkeypatch.setattr(api.traceback, "print_exc", lambda: None)

    res = client.post("/family/cue", json={"cue": CUE, "action": TAKE})

    assert res.status_code == 500
    assert res.json() == {"ok": False, "error": "joe failed acting on the cue: "
                                                "RuntimeError: can't start new thread"}
    assert client.get("/family/state").json() == {
        "member": "joe", "cue": None, "state": {"latest": None, "busy": False, "error": None}}


# ─── GET /family/identity, and the instance on each answer ────────────────────

def test_the_identity_says_what_joe_is_and_which_contract_it_keeps(client):
    res = client.get("/family/identity")

    assert res.status_code == 200
    identity = res.json()
    instance = identity.pop("instance")
    assert identity == {"member": "joe", "family": "performer-display", "version": "0",
                        "contract": "family/1", "conformance": "0.0.1", "verbs": ["take"],
                        "pid": os.getpid()}
    assert len(instance) == 12 and int(instance, 16) >= 0


def test_the_api_s_own_member_carries_the_api_s_version():
    assert api.family.identity()["version"] == api.app.version


def test_each_answer_to_a_cue_names_the_instance_the_identity_names(client):
    instance = client.get("/family/identity").json()["instance"]

    first = client.post("/family/cue", json={"cue": CUE, "action": TAKE})
    second = client.post("/family/cue", json={"cue": {**CUE, "number": "4"}, "action": TAKE})
    settled(client)

    assert first.json()["instance"] == second.json()["instance"] == instance


def test_a_joe_started_again_is_another_instance(tmp_path):
    def member():
        return Family.Member(audio_dir=tmp_path, output_dir=tmp_path, run=lambda path: 0)

    assert member().instance != member().instance


@pytest.mark.parametrize("path", ["/family/state", "/family/identity"])
def test_the_get_routes_answer_a_page_at_any_origin(client, path):
    res = client.get(path, headers={"Origin": "http://127.0.0.1:6283"})

    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "*"


# ─── GET /family/events ───────────────────────────────────────────────────────

class _Request:
    """A request that disconnects after `polls` checks, each preceded by `then`."""

    def __init__(self, polls: int, then=lambda: None):
        self.polls, self.then = polls, then

    async def is_disconnected(self) -> bool:
        self.then()
        self.polls -= 1
        return self.polls < 0


def _stream(request, heartbeat: float = 15.0) -> list[str]:
    async def collect():
        return [chunk async for chunk in api._family_events(request, poll=0, heartbeat=heartbeat)]
    return asyncio.run(collect())


def _states(chunks: list[str]) -> list[dict]:
    assert all(c.startswith("event: state\ndata: ") and c.endswith("\n\n")
               for c in chunks if not c.startswith(":"))
    return [json.loads(c.split("data: ", 1)[1]) for c in chunks if not c.startswith(":")]


def test_the_stream_opens_with_the_state_as_it_stands(client, pipeline):
    assert _states(_stream(_Request(polls=0))) == [client.get("/family/state").json()]


def test_a_cue_reaches_a_follower_and_so_does_its_take_finishing(client, pipeline):
    pipeline.release.clear()
    steps = iter([
        lambda: client.post("/family/cue", json={"cue": CUE, "action": TAKE}),
        lambda: (pipeline.release.set(), settled(client)),
    ])

    states = _states(_stream(_Request(polls=2, then=lambda: next(steps, lambda: None)())))

    assert [(s["cue"], s["state"]["busy"]) for s in states] == [
        (None, False), (CUE, True), (CUE, False)]
    assert states[-1] == client.get("/family/state").json()
    assert states[-1]["state"]["latest"]["events"] == EVENTS


def test_a_follower_behind_is_sent_the_newest_state_not_a_backlog(client, pipeline):
    pipeline.release.clear()
    second = {**CUE, "number": "4", "name": "Third tune"}

    def two_cues():
        client.post("/family/cue", json={"cue": CUE, "action": TAKE})
        client.post("/family/cue", json={"cue": second, "action": TAKE})

    steps = iter([two_cues])
    states = _states(_stream(_Request(polls=1, then=lambda: next(steps, lambda: None)())))
    pipeline.release.set()

    assert [s["cue"] for s in states] == [None, second]


def test_a_refused_cue_sends_a_follower_nothing(client, pipeline):
    steps = iter([lambda: client.post("/family/cue", json={"cue": CUE, "action": {"clock": "start"}})])

    chunks = _stream(_Request(polls=1, then=lambda: next(steps, lambda: None)()))

    assert len(chunks) == 1


def test_a_quiet_stream_is_kept_open_by_a_comment(client, pipeline):
    assert _stream(_Request(polls=2), heartbeat=0)[1:] == [": still here\n\n"] * 2
    assert _stream(_Request(polls=2))[1:] == []  # nothing in under fifteen seconds


# ─── End to end: the real API and the real pipeline ───────────────────────────

def _call(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_a_cue_s_take_runs_through_the_real_pipeline_and_is_reported(tmp_path):
    """`joe serve`'s API, under uvicorn from the checkout, and main.py for real.

    The take lands in the checkout's Data/ as the page's recordings do; it,
    its outputs and any folder this run made are removed afterwards.
    `JOE_WALKTHROUGH_PORTS` keeps the port inside a range.
    """
    from walkthrough.support import STARTUP_TIMEOUT, _folders, _port, _stop, _tidy

    port = _port()
    base = f"http://127.0.0.1:{port}"
    before = _folders()
    audio = REPO / "Data" / "Audio"
    there = set(audio.glob("cue-3_*.wav")) if audio.is_dir() else set()
    log = open(tmp_path / "api.log", "wb")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=REPO, env={**os.environ, "JOE_CUES": "0", "JOE_DATAPOINTS": "0",
                       # The cue's own capability, and the library's for what the page reads.
                       "JOE_ALLOW_FAMILY": "1", "JOE_ALLOW_LIBRARY": "1"},
        stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            assert server.poll() is None, (tmp_path / "api.log").read_text(errors="replace")
            try:
                if _call("GET", f"{base}/api/health")[0] == 200:
                    break
            except (urllib.error.URLError, OSError):
                pass
            assert time.monotonic() < deadline, "the API never answered"
            time.sleep(0.25)

        status, identity = _call("GET", f"{base}/family/identity")
        assert status == 200 and identity["member"] == "joe" and identity["pid"] == server.pid

        status, accepted = _call("POST", f"{base}/family/cue", {"cue": CUE, "action": TAKE})
        assert status == 202, accepted
        assert accepted["ok"] is True and accepted["state"]["busy"] is True
        assert accepted["instance"] == identity["instance"]

        deadline = time.monotonic() + 150
        while True:
            status, reported = _call("GET", f"{base}/family/state")
            assert status == 200
            if not reported["state"]["busy"]:
                break
            assert time.monotonic() < deadline, f"the take never finished: {reported}"
            time.sleep(0.5)
        latest = reported["state"]["latest"]

        assert reported["member"] == "joe" and reported["cue"] == CUE
        assert reported["state"]["error"] is None, reported["state"]["error"]
        assert latest["file"].startswith("cue-3_") and latest["file"].endswith(".wav")
        assert latest["events"] > 0

        # What the page shows agrees: the library lists the take, and the newest
        # result is the take's, holding as many events as the page counts.
        library = _call("GET", f"{base}/api/audio/files")[1]
        assert latest["file"] in [f["name"] for f in library]
        served = _call("GET", f"{base}/api/results/latest")[1]
        track = Path(latest["file"]).stem
        assert list(served["audio"]) == [track]
        counted = sum(len(note["start_dur"])
                      for transform in served["audio"][track]["chroma"].values()
                      for note in transform["midi"]["notes"])
        assert counted == latest["events"]
    finally:
        _stop(server)
        log.close()
        # Every take this run made, finished or not.
        made = set(audio.glob("cue-3_*.wav")) - there if audio.is_dir() else set()
        _tidy([p.name for p in made], before)
