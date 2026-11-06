"""joe held to the family contract's vector set, member side, over a real socket.

hearth (quaternionmedia/hearth) publishes `family/1`: `docs/contract.md` is the
contract and `conformance/vectors.json` the cases its own `hearth check`
asserts, under one version. A member pins the version it replayed in its own
suite and names it as `conformance` on its identity. This is joe's replay, by
a runner of its own -- joe does not import hearth -- against the real API
under uvicorn, with the pipeline stood in for.

`PINNED` and the line the replay prints are read by the corpus's interop
registry, so neither changes shape without it.
"""

import json
import threading
import time

import httpx
import pytest
import uvicorn

import api
from Modules import Family
from tests.test_family import Pipeline
from walkthrough.support import _port

PINNED = "0.0.1"

# The member side of the vector set at PINNED, by id, in the order asked.
CASES = [
    "identity-answers",
    "identity-is-an-object",
    "identity-keeps-contract",
    "identity-names-member",
    "identity-names-family",
    "identity-names-instance",
    "identity-names-conformance",
    "state-shape",
    "cue-not-json-refused",
    "cue-unknown-action-refused",
    "refused-cue-changes-nothing",
    "events-state-at-once",
    "action-taken",
    "cue-reaches-follower",
]
# One real action, which the last two cases need: joe's only verb.
ACTION = {"take": {"notes": ["C4"], "seconds_per_note": 0.25}}
TIMEOUT = 5.0


@pytest.fixture
def joe(tmp_path, monkeypatch):
    """The API under uvicorn on a port of its own, lifespan and guard included,
    and the pipeline standing in for main.py."""
    pipeline = Pipeline(tmp_path / "Output")
    monkeypatch.setattr(api, "family", Family.Member(
        audio_dir=tmp_path / "Audio", output_dir=tmp_path / "Output",
        run=pipeline, version=api.app.version))
    port = _port()
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="on", ws="none"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the API did not start"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}", pipeline
    finally:
        pipeline.release.set()
        server.should_exit = True
        thread.join(30)


def states(response):
    """Each `state` event's data from an open stream, as it arrives."""
    name, data = None, []
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and data:
            if name == "state":
                yield json.loads("\n".join(data))
            name, data = None, []


def refused(response) -> bool:
    """422 in the contract's shape: `{"ok": false, "error": "..."}`."""
    body = response.json()
    return (response.status_code == 422 and body.get("ok") is False
            and isinstance(body.get("error"), str) and bool(body["error"]))


def test_joe_passes_every_member_case_of_the_pinned_vector_set(joe):
    url, pipeline = joe
    assert Family.CONFORMANCE == PINNED  # what the identity claims is what is replayed here
    passed = []

    def case(name: str, held: bool, saw: object = "") -> None:
        assert name == CASES[len(passed)], f"{name} asked out of the vector set's order"
        assert held, f"{name}: {saw}"
        passed.append(name)

    with httpx.Client(base_url=url, timeout=TIMEOUT) as client:
        said = client.get("/family/identity")
        case("identity-answers", True)
        identity = said.json()
        case("identity-is-an-object", said.status_code == 200 and isinstance(identity, dict),
             f"{said.status_code} {identity}")
        case("identity-keeps-contract", identity.get("contract") == "family/1", identity)
        for key in ("member", "family", "instance", "conformance"):
            case(f"identity-names-{key}", isinstance(identity.get(key), str) and identity[key],
                 identity)

        said = client.get("/family/state")
        before = said.json()
        case("state-shape", said.status_code == 200 and before.get("member") == identity["member"]
             and "cue" in before and isinstance(before.get("state"), dict), before)

        said = client.post("/family/cue", content=b"{not json",
                           headers={"Content-Type": "application/json"})
        case("cue-not-json-refused", refused(said), f"{said.status_code} {said.text}")
        cue = {"number": "conformance", "name": "conformance", "fired_at": None}
        said = client.post("/family/cue", json={"cue": cue, "action": {"no-verb-of-joe-s": True}})
        case("cue-unknown-action-refused", refused(said), f"{said.status_code} {said.text}")
        after = client.get("/family/state").json()
        case("refused-cue-changes-nothing", after == before, f"{before} then {after}")

        with client.stream("GET", "/family/events") as stream:
            assert stream.status_code == 200
            assert "text/event-stream" in stream.headers["content-type"]
            following = states(stream)
            first = next(following)
            case("events-state-at-once", first == before, first)

            # Fired once the stream is open, so the event it causes cannot be missed,
            # and with the take held, so that event is the cue's and not its take's end.
            pipeline.release.clear()
            fired = {**cue, "number": f"conformance-{time.time_ns()}"}
            said = client.post("/family/cue", json={"cue": fired, "action": ACTION})
            answer = said.json()
            case("action-taken", said.status_code in (200, 202) and answer.get("ok") is True
                 and answer.get("instance") == identity["instance"], f"{said.status_code} {answer}")
            try:
                reached = next(s for s in following
                               if (s.get("cue") or {}).get("number") == fired["number"])
            except (StopIteration, httpx.ReadTimeout):
                reached = None
            case("cue-reaches-follower", reached is not None and reached["member"] == "joe"
                 and reached["state"]["busy"] is True,
                 f"no state event named cue {fired['number']} within {TIMEOUT:g} s")
            pipeline.release.set()

    assert passed == CASES
    print(f"\nfamily/1 conformance: {len(passed)} applicable, all passing; "
          f"{len(CASES) - len(passed)} not applicable")
