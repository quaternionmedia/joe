"""`joe backend` and `joe dev`: the disclaimer first, and `--allow` for each
capability the API should serve beyond the media API. `joe dev` with no
`--allow` serves every one, on loopback."""

import os

import pytest
from typer.testing import CliRunner

import cli
from Modules import Access

runner = CliRunner()


@pytest.fixture
def started(monkeypatch):
    """The commands each process would start, with the environment it gets;
    nothing is started. No JOE_ALLOW_ setting is inherited."""
    for name in list(os.environ):
        if name.startswith(Access.PREFIX):
            monkeypatch.delenv(name)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs.get("env")))

    class Process:
        pid = 0

        def __init__(self, args, **kwargs):
            calls.append((args, kwargs.get("env")))

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli.subprocess, "Popen", Process)
    return calls


def allowed(env) -> dict[str, bool]:
    return Access.allowed_map(env)


def api(calls):
    """The environment the API was started with."""
    return next(env for args, env in calls if "uvicorn" in args)


def test_the_backend_says_it_has_no_authentication_and_serves_the_media_api_alone(started):
    result = runner.invoke(cli.app, ["backend"])

    assert result.exit_code == 0
    assert "joe has no authentication" in result.output
    assert "127.0.0.1:8000" in result.output and "docs/security.md" in result.output
    assert allowed(api(started)) == {
        "media": True, "microphone": False, "transcripts": False, "library": False}


def test_each_allow_turns_its_capability_on_for_the_api(started):
    result = runner.invoke(cli.app, ["backend", "--allow", "microphone", "--allow", "Library"])

    assert result.exit_code == 0
    env = api(started)
    assert env["JOE_ALLOW_MICROPHONE"] == "1" and env["JOE_ALLOW_LIBRARY"] == "1"
    assert allowed(env) == {"media": True, "microphone": True, "transcripts": False, "library": True}


def test_allow_all_turns_every_one_on(started):
    assert runner.invoke(cli.app, ["backend", "--allow", "all"]).exit_code == 0
    assert all(allowed(api(started)).values())


def test_a_name_that_is_no_capability_starts_nothing(started):
    result = runner.invoke(cli.app, ["backend", "--allow", "camera"])

    assert result.exit_code == 2
    assert "'camera' is no capability of joe's" in result.output
    assert started == []


def uvicorn(calls):
    """The command the API was started with."""
    return next(args for args, env in calls if "uvicorn" in args)


def test_the_api_listens_on_loopback_alone(started):
    for command in (["backend"], ["dev"]):
        started.clear()
        assert runner.invoke(cli.app, command).exit_code == 0
        args = uvicorn(started)
        assert args[args.index("--host") + 1] == "127.0.0.1", command


def test_dev_with_no_allow_turns_every_capability_on_and_says_so(started):
    result = runner.invoke(cli.app, ["dev"])

    assert result.exit_code == 0
    assert "joe has no authentication" in result.output
    assert "joe dev turns every capability on" in result.output
    assert all(allowed(api(started)).values())


def test_dev_keeps_a_setting_the_environment_already_has(started, monkeypatch):
    monkeypatch.setenv("JOE_ALLOW_MICROPHONE", "0")

    assert runner.invoke(cli.app, ["dev"]).exit_code == 0
    assert allowed(api(started)) == {
        "media": True, "microphone": False, "transcripts": True, "library": True}


def test_dev_allow_media_serves_the_media_api_alone(started):
    result = runner.invoke(cli.app, ["dev", "--allow", "media"])

    assert result.exit_code == 0
    assert "turns every capability on" not in result.output
    assert allowed(api(started)) == {
        "media": True, "microphone": False, "transcripts": False, "library": False}


def test_dev_hands_the_api_what_allow_says_and_leaves_vite_alone(started):
    result = runner.invoke(cli.app, ["dev", "--allow", "transcripts"])

    assert result.exit_code == 0
    assert "joe has no authentication" in result.output
    assert allowed(api(started)) == {
        "media": True, "microphone": False, "transcripts": True, "library": False}
    vite = next(env for args, env in started if "uvicorn" not in args)
    assert vite is None  # Vite inherits this environment as it is
