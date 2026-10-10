"""
Containment checks for the two routes that take a filename from the client:
GET /api/audio/{filename} and POST /api/run/{filename}.

Each route must serve only a bare filename that lives inside AUDIO_DIR and
answer 404 for anything else, without revealing whether the target exists.
"""

from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api

GOOD = "good.wav"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
OUTSIDE_MARKER = b'[project]\nname = "outside"\n'

# Request paths that must be answered 404 by both routes. Some are rejected by
# the router (a decoded slash splits the segment), the rest by the handler.
BAD_REQUEST_NAMES = [
    pytest.param("..%5C..%5Cpyproject.toml", id="backslash-traversal"),
    pytest.param("..%2F..%2Fpyproject.toml", id="slash-traversal"),
    pytest.param(quote(str(PYPROJECT), safe=""), id="absolute-path"),
    pytest.param("sub%2Fgood.wav", id="encoded-forward-slash"),
    pytest.param("sub/good.wav", id="forward-slash"),
    # Windows opens good.wav for these; the route must not offer the alias
    pytest.param(f"{GOOD}.", id="trailing-dot"),
    pytest.param(f"{GOOD}%20", id="trailing-space"),
    # a NUL byte would raise ValueError from the filesystem call, not 404
    pytest.param(f"{GOOD}%00", id="nul-byte"),
]

# Names as the handler receives them; the HTTP client normalises "." and ".."
# segments away before they reach the server, so these are checked directly.
BAD_HANDLER_NAMES = [
    pytest.param("", id="empty"),
    pytest.param(".", id="dot"),
    pytest.param("..", id="dot-dot"),
    pytest.param("..\\..\\pyproject.toml", id="backslash-traversal"),
    pytest.param("../../pyproject.toml", id="slash-traversal"),
    pytest.param(str(PYPROJECT), id="absolute-path"),
    pytest.param("sub/good.wav", id="forward-slash"),
    pytest.param("sub\\good.wav", id="backslash"),
    pytest.param(f"{GOOD}.", id="trailing-dot"),
    pytest.param(f"{GOOD} ", id="trailing-space"),
    pytest.param(f"{GOOD}\x00", id="nul-byte"),
]


@pytest.fixture
def audio_dir(tmp_path, monkeypatch):
    """
    Point AUDIO_DIR at <tmp>/Data/Audio holding one file, mirroring the
    project layout, with a pyproject.toml two levels up so that a
    parent-directory escape has a real target to reveal.
    """
    audio_dir = tmp_path / "Data" / "Audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / GOOD).write_bytes(b"RIFF")
    (tmp_path / "pyproject.toml").write_bytes(OUTSIDE_MARKER)
    monkeypatch.setattr(api, "AUDIO_DIR", audio_dir)
    return audio_dir


@pytest.fixture
def client(audio_dir):
    return TestClient(api.app)


@pytest.fixture
def no_subprocess(monkeypatch):
    """Replace the pipeline subprocess so POST /api/run/{filename} runs nothing."""
    calls = []

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr(api.asyncio, "create_subprocess_exec", fake_exec)
    return calls


# ─── _audio_file ──────────────────────────────────────────────────────────────

def test_audio_file_resolves_bare_name_inside_audio_dir(audio_dir):
    assert api._audio_file(GOOD) == (audio_dir / GOOD).resolve()


@pytest.mark.parametrize("name", BAD_HANDLER_NAMES)
def test_audio_file_rejects_non_bare_names(audio_dir, name):
    with pytest.raises(HTTPException) as excinfo:
        api._audio_file(name)
    assert excinfo.value.status_code == 404


def test_audio_file_rejects_missing_file(audio_dir):
    with pytest.raises(HTTPException) as excinfo:
        api._audio_file("absent.wav")
    assert excinfo.value.status_code == 404


# ─── GET /api/audio/{filename} ────────────────────────────────────────────────

def test_audio_serve_returns_file_inside_audio_dir(client):
    res = client.get(f"/api/audio/{GOOD}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/wav")
    assert res.content == b"RIFF"


@pytest.mark.parametrize("name", BAD_REQUEST_NAMES)
def test_audio_serve_rejects_non_bare_names(client, name):
    res = client.get(f"/api/audio/{name}")
    assert res.status_code == 404
    assert OUTSIDE_MARKER not in res.content
    assert PYPROJECT.read_bytes() != res.content


def test_audio_serve_missing_file_is_404(client):
    res = client.get("/api/audio/absent.wav")
    assert res.status_code == 404


# ─── POST /api/run/{filename} ─────────────────────────────────────────────────

def test_run_on_file_runs_pipeline_for_file_inside_audio_dir(client, no_subprocess):
    res = client.post(f"/api/run/{GOOD}")
    assert res.status_code == 200
    assert res.json() == {"returncode": 0, "stdout": "ok", "stderr": ""}
    assert len(no_subprocess) == 1
    (_, kwargs), = no_subprocess
    assert Path(kwargs["env"]["JOE_AUDIO_FILE"]) == (api.AUDIO_DIR / GOOD).resolve()


@pytest.mark.parametrize("name", BAD_REQUEST_NAMES)
def test_run_on_file_rejects_non_bare_names(client, no_subprocess, name):
    res = client.post(f"/api/run/{name}")
    assert res.status_code == 404
    assert no_subprocess == []


def test_run_on_file_missing_file_is_404(client, no_subprocess):
    res = client.post("/api/run/absent.wav")
    assert res.status_code == 404
    assert no_subprocess == []


# ─── _resolve_audio_path (the voice routes) ───────────────────────────────────
#
# POST /api/voice/transcribe takes a filename too. Its resolver and the audio
# routes' share `_is_bare_filename`, and these hold them to the same list.
#
# It resolves against a relative `Data/Audio` and `Data/Voice` rather than
# AUDIO_DIR, so the fixture below moves the working directory instead of
# patching a module attribute.

@pytest.fixture
def voice_dirs(tmp_path, monkeypatch):
    """A Data/Audio and Data/Voice under a temporary working directory.

    `exist_ok` because the agreement test below asks for `audio_dir` too,
    and both fixtures build under the same `tmp_path`.
    """
    for name in ("Audio", "Voice"):
        (tmp_path / "Data" / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "Data" / "Audio" / GOOD).write_bytes(b"RIFF")
    (tmp_path / "pyproject.toml").write_bytes(OUTSIDE_MARKER)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_resolve_audio_path_resolves_bare_name(voice_dirs):
    resolved = api._resolve_audio_path(GOOD)
    assert resolved == (voice_dirs / "Data" / "Audio" / GOOD).resolve()


def test_resolve_audio_path_finds_a_file_under_data_voice(voice_dirs):
    (voice_dirs / "Data" / "Voice" / "spoken.wav").write_bytes(b"RIFF")
    assert api._resolve_audio_path("spoken.wav").name == "spoken.wav"


@pytest.mark.parametrize("name", BAD_HANDLER_NAMES)
def test_resolve_audio_path_rejects_non_bare_names(voice_dirs, name):
    """The same list the audio route is held to, including the aliases.

    `good.wav.` and `"good.wav "` alias a file that exists, so a resolver
    checking only containment would return it, and the endpoint would
    transcribe a file under a name no listing shows.
    """
    with pytest.raises(HTTPException) as excinfo:
        api._resolve_audio_path(name)
    assert excinfo.value.status_code == 404


def test_resolve_audio_path_rejects_missing_file(voice_dirs):
    with pytest.raises(HTTPException) as excinfo:
        api._resolve_audio_path("absent.wav")
    assert excinfo.value.status_code == 404


@pytest.mark.parametrize("name", BAD_HANDLER_NAMES)
def test_both_resolvers_agree_on_every_bad_name(audio_dir, voice_dirs, name):
    """Both resolvers give every bad name the same answer."""
    for resolver in (api._audio_file, api._resolve_audio_path):
        with pytest.raises(HTTPException) as excinfo:
            resolver(name)
        assert excinfo.value.status_code == 404, f"{resolver.__name__} allowed {name!r}"
