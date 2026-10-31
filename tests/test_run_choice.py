"""Which recordings a run of the pipeline analyses -- the newest, those named, or
every one -- as `joe run`, `POST /api/run` and `main.py` take it."""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import api
import cli
from Modules.utilities import audio_files


def _recordings(folder, *names):
    """`names` in `folder`, each written a second after the one before it."""
    folder.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        path = folder / name
        path.write_bytes(b"RIFF")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
    return folder


# ─── audio_files ──────────────────────────────────────────────────────────────

def test_a_run_told_nothing_analyses_the_newest_recording(tmp_path):
    folder = _recordings(tmp_path, "b.wav", "c.mp3", "a.flac")
    assert audio_files(folder) == [str(folder / "a.flac")]


def test_every_recording_is_every_audio_file_by_name(tmp_path):
    folder = _recordings(tmp_path, "b.wav", "notes.txt", "a.flac", "c.webm")
    (folder / ".incoming").mkdir()
    assert audio_files(folder, every=True) == [str(folder / n) for n in ("a.flac", "b.wav", "c.webm")]


def test_recordings_named_are_those_in_the_order_named(tmp_path):
    folder = _recordings(tmp_path, "a.wav", "b.wav", "c.wav")
    assert audio_files(folder, names=["c.wav", "a.wav"]) == [str(folder / "c.wav"), str(folder / "a.wav")]


@pytest.mark.parametrize("name", ["absent.wav", "notes.txt", "../a.wav", "sub/a.wav"])
def test_a_name_that_is_no_recording_here_is_refused(tmp_path, name):
    folder = _recordings(tmp_path, "a.wav", "notes.txt")
    with pytest.raises(ValueError, match="no recording"):
        audio_files(folder, names=[name])


def test_a_folder_with_no_recording_has_none_to_analyse(tmp_path):
    folder = _recordings(tmp_path, "notes.txt")
    assert audio_files(folder) == []
    assert audio_files(folder, every=True) == []


# ─── POST /api/run, POST /api/run/{filename} ─────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "AUDIO_DIR", _recordings(tmp_path / "Data" / "Audio", "a.wav", "b.wav", "notes.txt"))
    return TestClient(api.app)


@pytest.fixture
def runs(monkeypatch):
    """The pipeline's command lines, run nothing."""
    calls = []

    class Done:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_exec(*args, **kwargs):
        calls.append(list(args))
        return Done()

    monkeypatch.setattr(api.asyncio, "create_subprocess_exec", fake_exec)
    return calls


def test_a_run_through_the_api_told_nothing_leaves_the_choice_to_the_pipeline(client, runs):
    assert client.post("/api/run").json()["returncode"] == 0
    assert runs == [[sys.executable, str(api._MAIN_PY)]]


def test_a_run_through_the_api_can_name_its_recordings(client, runs):
    assert client.post("/api/run?files=b.wav&files=a.wav").status_code == 200
    assert runs == [[sys.executable, str(api._MAIN_PY), "b.wav", "a.wav"]]


def test_a_run_through_the_api_can_ask_for_every_recording(client, runs):
    assert client.post("/api/run?all=true").status_code == 200
    assert runs == [[sys.executable, str(api._MAIN_PY), "--all"]]


@pytest.mark.parametrize("name", ["absent.wav", "notes.txt", "..%2Fa.wav"])
def test_a_run_naming_what_is_no_recording_is_refused_and_runs_nothing(client, runs, name):
    assert client.post(f"/api/run?files={name}").status_code == 404
    assert runs == []


def test_a_run_naming_recordings_and_asking_for_all_is_refused(client, runs):
    res = client.post("/api/run?files=a.wav&all=true")
    assert res.status_code == 400
    assert "not both" in res.json()["detail"]
    assert runs == []


def test_a_run_on_one_file_names_it_to_the_pipeline(client, runs):
    assert client.post("/api/run/b.wav").status_code == 200
    assert runs == [[sys.executable, str(api._MAIN_PY), "b.wav"]]


# ─── joe run ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pipeline(monkeypatch):
    """`joe run`'s command lines, run nothing."""
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kwargs: calls.append(list(args)) or Done())
    return calls


@pytest.mark.parametrize("args, passed", [
    ([], []),
    (["--all"], ["--all"]),
    (["b.wav", "a.wav"], ["b.wav", "a.wav"]),
])
def test_joe_run_hands_the_pipeline_its_choice(pipeline, args, passed):
    result = CliRunner().invoke(cli.app, ["run", *args])
    assert result.exit_code == 0, result.output
    assert pipeline == [[sys.executable, "main.py", *passed]]


def test_joe_run_naming_recordings_and_asking_for_all_is_refused(pipeline):
    result = CliRunner().invoke(cli.app, ["run", "--all", "a.wav"])
    assert result.exit_code == 2
    assert "not both" in result.output
    assert pipeline == []
