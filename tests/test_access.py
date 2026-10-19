"""What a fresh joe serves, and what each JOE_ALLOW_ setting turns on.

joe has no authentication. A fresh joe serves the media API, which alfred
needs, and nothing that records or hands data out: the microphone, the
transcripts and the audio library each answer 403, naming the setting that
turns them on, until it is set. These tests start from that fresh joe; every
other test module finds every capability on (`conftest._every_capability_on`).
"""

import os

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import api
from Modules import Access

ID = "0123456789abcdef0123456789abcdef"

# Every route, and the capability it belongs to; None for one always served.
ROUTES = {
    ("GET", "/api/health"): None,
    ("GET", "/api/voice/vocabulary"): None,
    ("GET", "/api/media/capabilities"): "media",
    ("POST", "/api/media"): "media",
    ("POST", "/api/media/{media_id}/transcribe"): "media",
    ("POST", "/api/media/{media_id}/analyze"): "media",
    ("DELETE", "/api/media/{media_id}"): "media",
    ("POST", "/api/capture/start"): "microphone",
    ("POST", "/api/capture/stop"): "microphone",
    ("GET", "/api/voice/devices"): "microphone",
    ("POST", "/api/voice/listen"): "microphone",
    ("POST", "/api/voice/watch"): "microphone",
    ("POST", "/api/voice/unwatch"): "microphone",
    ("POST", "/api/voice/level"): "microphone",
    ("POST", "/api/voice/answer"): "microphone",
    ("POST", "/api/voice/hold"): "microphone",
    ("POST", "/api/voice/strike"): "microphone",
    ("GET", "/api/voice/control"): "microphone",
    ("POST", "/api/voice/conversation"): "microphone",
    ("GET", "/api/voice/conversation"): "transcripts",
    ("GET", "/api/voice/conversation/state"): "transcripts",
    ("GET", "/api/voice/history"): "transcripts",
    ("GET", "/api/voice/transcript"): "transcripts",
    ("GET", "/api/results/latest"): "library",
    ("POST", "/api/run"): "library",
    ("POST", "/api/run/{filename}"): "library",
    ("POST", "/api/audio/upload"): "library",
    ("GET", "/api/audio/files"): "library",
    ("GET", "/api/audio/{filename}"): "library",
    ("POST", "/api/voice/transcribe"): "library",
}


def _called(path: str) -> str:
    return path.replace("{media_id}", ID).replace("{filename}", "x.wav")


GATED = [pytest.param(method, path, name, id=f"{method} {path}")
         for (method, path), name in ROUTES.items() if name]


@pytest.fixture
def fresh(monkeypatch):
    """A joe as downloaded: no JOE_ALLOW_ setting at all."""
    for name in list(os.environ):
        if name.startswith(Access.PREFIX):
            monkeypatch.delenv(name)


@pytest.fixture
def client(fresh):
    return TestClient(api.app)


# ─── The settings ─────────────────────────────────────────────────────────────

def test_a_fresh_joe_serves_the_media_api_and_nothing_else():
    assert Access.allowed_map({}) == {
        "media": True, "microphone": False, "transcripts": False, "library": False}


@pytest.mark.parametrize("name", list(Access.CAPABILITIES))
@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_each_setting_turns_its_capability_on(name, value):
    setting = Access.CAPABILITIES[name].setting
    assert Access.allowed_map({setting: value}) == {
        other: other == name or Access.CAPABILITIES[other].default for other in Access.CAPABILITIES}


@pytest.mark.parametrize("name", list(Access.CAPABILITIES))
@pytest.mark.parametrize("value", ["0", "false", "No", "off", ""])
def test_each_setting_turns_its_capability_off(name, value):
    assert Access.allowed(name, {Access.CAPABILITIES[name].setting: value}) is False


def test_the_settings_are_named_after_their_capabilities():
    assert [c.setting for c in Access.CAPABILITIES.values()] == [
        "JOE_ALLOW_MEDIA", "JOE_ALLOW_MICROPHONE", "JOE_ALLOW_TRANSCRIPTS", "JOE_ALLOW_LIBRARY"]


def test_a_setting_that_cannot_be_read_is_off_and_is_a_problem():
    env = {"JOE_ALLOW_MICROPHONE": "maybe", "JOE_ALLOW_MEDIA": "2"}

    assert Access.allowed("microphone", env) is False
    assert Access.allowed("media", env) is False  # off, though media's default is on
    assert Access.problems(env) == ["JOE_ALLOW_MEDIA='2' is neither 1 nor 0",
                                    "JOE_ALLOW_MICROPHONE='maybe' is neither 1 nor 0"]


def test_a_misspelt_setting_is_a_problem_rather_than_nothing():
    found = Access.problems({"JOE_ALLOW_MICROPONE": "1"})

    assert len(found) == 1
    assert found[0].startswith("JOE_ALLOW_MICROPONE is no capability of joe's")
    assert "JOE_ALLOW_MICROPHONE" in found[0]


def test_readable_settings_are_no_problem():
    assert Access.problems({}) == []
    assert Access.problems({c.setting: "1" for c in Access.CAPABILITIES.values()}) == []
    assert Access.problems({"JOE_CUES": "0", "PATH": "x"}) == []


def test_a_refusal_names_the_setting_that_turns_it_on():
    for name, capability in Access.CAPABILITIES.items():
        said = Access.refusal(name)
        assert said.startswith(f"{capability.title} is off on this joe: {capability.setting}=1 turns it on")
        assert "no authentication" in said and "docs/security.md" in said


# ─── What the server says as it starts ────────────────────────────────────────

def test_the_banner_says_there_is_no_authentication_and_what_is_on():
    lines = Access.banner({})

    assert lines[0].startswith("joe: NO AUTHENTICATION.")
    assert "loopback" in lines[1] and "docs/security.md" in lines[1]
    states = [line.split()[1:3] for line in lines[2:]]
    assert states == [["on", "media"], ["off", "microphone"], ["off", "transcripts"], ["off", "library"]]
    assert "JOE_ALLOW_MEDIA=0 turns it off" in lines[2]
    assert all(f"{c.setting}=1 turns it on" in line
               for c, line in zip(list(Access.CAPABILITIES.values())[1:], lines[3:]))
    assert not any("WARNING" in line for line in lines)


@pytest.mark.parametrize("name", ["microphone", "transcripts", "library"])
def test_each_capability_turned_on_is_warned_about(name):
    capability = Access.CAPABILITIES[name]
    lines = Access.banner({capability.setting: "1"})

    warnings = [line for line in lines if "WARNING" in line]
    assert warnings == [(f"joe: !!! WARNING: {capability.setting}=1. Whatever can reach this port "
                         f"{capability.exposes}.")]
    assert f"joe: on   {name}" in "\n".join(lines)


def test_media_on_by_default_is_not_warned_about_and_off_is_said():
    assert not any("WARNING" in line for line in Access.banner({"JOE_ALLOW_MEDIA": "1"}))
    assert any(line.startswith("joe: off  media") for line in Access.banner({"JOE_ALLOW_MEDIA": "0"}))


def test_the_server_prints_the_banner_as_it_starts(fresh, monkeypatch, capsys):
    monkeypatch.setenv("JOE_ALLOW_MICROPHONE", "1")
    with TestClient(api.app):
        pass

    said = capsys.readouterr().err
    assert "joe: NO AUTHENTICATION." in said
    assert "joe: !!! WARNING: JOE_ALLOW_MICROPHONE=1." in said
    assert "JOE_ALLOW_LIBRARY=1 turns it on" in said


def test_the_server_will_not_start_on_a_setting_it_cannot_read(fresh, monkeypatch, capsys):
    monkeypatch.setenv("JOE_ALLOW_LIBRARY", "please")
    with pytest.raises(RuntimeError, match="will not start"), TestClient(api.app):
        pass

    assert "joe: JOE_ALLOW_LIBRARY='please' is neither 1 nor 0" in capsys.readouterr().err


# ─── The routes ───────────────────────────────────────────────────────────────

def test_every_route_belongs_to_the_capability_this_table_says():
    """A route added without a capability fails here, not in a security review."""
    served = {}
    for route in api.app.routes:
        if not isinstance(route, APIRoute):
            continue  # FastAPI's own /openapi.json and /docs
        needs = [d.call.capability for d in route.dependant.dependencies
                 if hasattr(d.call, "capability")]
        assert len(needs) <= 1, route.path
        for method in route.methods:
            served[(method, route.path)] = needs[0] if needs else None

    assert served == ROUTES


@pytest.mark.parametrize("method, path, name", GATED)
def test_a_capability_that_is_off_answers_403_naming_its_setting(method, path, name, client, monkeypatch):
    monkeypatch.setenv("JOE_ALLOW_MEDIA", "0")
    response = client.request(method, _called(path))

    assert response.status_code == 403
    assert response.json() == {"detail": Access.refusal(name)}


@pytest.mark.parametrize("method, path, name", GATED)
def test_no_other_setting_lets_a_route_past(method, path, name, client, monkeypatch):
    """Every capability on but this route's own, and it is still refused."""
    for other, capability in Access.CAPABILITIES.items():
        monkeypatch.setenv(capability.setting, "0" if other == name else "1")

    assert client.request(method, _called(path)).json() == {"detail": Access.refusal(name)}


@pytest.mark.parametrize("setting, method, path", [
    ("JOE_ALLOW_MEDIA", "GET", "/api/media/capabilities"),
    ("JOE_ALLOW_MICROPHONE", "GET", "/api/voice/control"),
    ("JOE_ALLOW_TRANSCRIPTS", "GET", "/api/voice/transcript"),
    ("JOE_ALLOW_LIBRARY", "GET", "/api/audio/files"),
])
def test_a_capability_turned_on_answers(setting, method, path, client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "AUDIO_DIR", tmp_path / "Audio")
    monkeypatch.setenv(setting, "1")

    assert client.request(method, path).status_code == 200


def test_the_media_api_answers_in_a_fresh_joe(client):
    """alfred's routes need no setting."""
    assert client.get("/api/media/capabilities").status_code == 200
    assert client.delete(f"/api/media/{ID}").status_code == 404
    assert client.post(f"/api/media/{ID}/analyze").status_code == 404


def test_a_refusal_comes_before_anything_the_route_was_asked(client, monkeypatch):
    """Out-of-bounds parameters are not judged, and nothing is recorded,
    answered, run or written, while the capability is off."""
    monkeypatch.setattr(api._capture, "start", lambda *a, **k: pytest.fail("recorded"))

    async def no_pipeline(*args, **kwargs):
        pytest.fail("ran the pipeline")

    monkeypatch.setattr(api.asyncio, "create_subprocess_exec", no_pipeline)
    before = api.control.snapshot(), api.conversation.snapshot()["events"]

    assert client.post("/api/voice/listen?duration=999").status_code == 403
    assert client.post("/api/capture/start").status_code == 403
    assert client.post("/api/voice/answer", json={"text": "approve"}).status_code == 403
    assert client.post("/api/voice/conversation", json={"state": "speaking", "text": "x"}).status_code == 403
    assert client.post("/api/run").status_code == 403
    assert (api.control.snapshot(), api.conversation.snapshot()["events"]) == before

    monkeypatch.setenv("JOE_ALLOW_MEDIA", "0")
    assert client.post(f"/api/media/{ID}/analyze?peaks_rate=0").status_code == 403


def test_nothing_is_written_to_the_library_while_it_is_off(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "AUDIO_DIR", tmp_path / "Audio")
    response = client.post("/api/audio/upload", content=b"RIFF", headers={"content-type": "audio/wav"})

    assert response.status_code == 403
    assert not (tmp_path / "Audio").exists()


def test_the_health_check_says_which_capabilities_are_on(client, monkeypatch):
    assert client.get("/api/health").json() == {"status": "ok", "allowed": {
        "media": True, "microphone": False, "transcripts": False, "library": False}}

    monkeypatch.setenv("JOE_ALLOW_TRANSCRIPTS", "1")
    assert client.get("/api/health").json()["allowed"]["transcripts"] is True


def test_the_vocabulary_is_always_served(client):
    assert client.get("/api/voice/vocabulary").status_code == 200
