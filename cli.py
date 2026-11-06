"""
Joe CLI - dev launcher for the Joe Audio Workbench.

Usage (with uv):
    uv run joe frontend   # Vite dev server only  (localhost:3000)
    uv run joe backend    # FastAPI server only    (127.0.0.1:8000): the media API alone
    uv run joe dev        # Both servers together, every capability on, on loopback
    uv run joe run        # Run the pipeline once  (Data/Audio/ -> Data/Output/)

joe has no authentication. `backend` serves the media API and nothing that
records or hands data out until `--allow` turns it on: `--allow microphone`,
`--allow transcripts`, `--allow library`, `--allow family`, or `--allow all`.
`dev` is for working on joe on this machine: with no `--allow` it turns every
capability on, and with one it serves what `backend` would (docs/security.md).

After `uv tool install -e .` the bare `joe` command works everywhere.
"""

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated

import typer


def _echo(message: str = "", err: bool = False) -> None:
    """typer.echo, surviving a console it cannot write to.

    Under a MinTTY terminal (Git Bash), click's Windows console writer can
    raise OSError -- Windows error 6, an invalid handle -- on the wrapped
    stderr, replacing the one diagnostic that mattered with a traceback.
    The message outranks its styling: fall back to the interpreter's
    original stream, which is a plain pipe on such terminals.
    """
    try:
        typer.echo(message, err=err)
    except OSError:
        stream = sys.__stderr__ if err else sys.__stdout__
        if stream is not None:
            stream.write(str(message) + "\n")
            stream.flush()


def _kill(proc: subprocess.Popen) -> None:
    """Kill a subprocess and its entire process tree, then wait for it to exit."""
    if sys.platform == "win32":
        # terminate() only kills the direct child; on Windows uvicorn --reload
        # spawns a server worker subprocess that would otherwise keep holding
        # the port.  taskkill /T kills the whole tree.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

Allow = Annotated[list[str] | None, typer.Option(
    "--allow", metavar="CAPABILITY",
    help="Turn a capability of the API on: media, microphone, transcripts, library, family, or all; "
         "repeat for more. joe has no authentication: whatever reaches the port gets what is on "
         "(docs/security.md).",
)]


def _api_env(allow: list[str] | None, everything: bool = False) -> dict[str, str]:
    """The API's environment: this one, with `JOE_ALLOW_<NAME>=1` for each
    capability `--allow` names, and every one for `all`. A name that is no
    capability is a usage error, before anything starts. `everything` turns on
    each capability this environment does not already set."""
    from Modules import Access

    env = dict(os.environ)
    if everything:
        for capability in Access.CAPABILITIES.values():
            env.setdefault(capability.setting, "1")
    for given in allow or []:
        name = given.strip().lower()
        if name == "all":
            names = list(Access.CAPABILITIES)
        elif name in Access.CAPABILITIES:
            names = [name]
        else:
            raise typer.BadParameter(
                f"{given!r} is no capability of joe's: there are {', '.join(Access.CAPABILITIES)}, "
                f"and all", param_hint="--allow")
        for each in names:
            env[Access.CAPABILITIES[each].setting] = "1"
    return env


def _disclaim() -> None:
    """What `backend` and `dev` say before anything starts."""
    _echo("joe has no authentication: whatever can reach the API's port is answered, with this "
          "account's rights.")
    _echo("The API listens on loopback, 127.0.0.1:8000, for this machine alone, and lists what it "
          "serves as it starts (docs/security.md).")


app = typer.Typer(
    help="Joe Audio Workbench - dev CLI",
    no_args_is_help=True,
)

voice_app = typer.Typer(help="Speech analysis: transcription and mic capture.", no_args_is_help=True)
app.add_typer(voice_app, name="voice")

# The API, on loopback alone: joe has no authentication.
_UVICORN = [sys.executable, "-m", "uvicorn", "api:app", "--reload",
            "--host", "127.0.0.1", "--port", "8000"]

# npm is 'npm.cmd' on Windows when not in a shell
_npm = "npm.cmd" if sys.platform == "win32" else "npm"


@app.command()
def frontend():
    """Start the Vite frontend dev server (localhost:3000)."""
    subprocess.run([_npm, "run", "dev"], check=False)


@app.command()
def backend(allow: Allow = None):
    """Start the FastAPI backend API server (127.0.0.1:8000).

    It serves the media API alone until `--allow` turns more on."""
    env = _api_env(allow)
    _disclaim()
    subprocess.run(
        _UVICORN,
        check=False,
        env=env,
    )


@app.command()
def dev(allow: Allow = None):
    """Start both frontend and backend dev servers. Ctrl+C stops both.

    With no `--allow`, the API serves every capability -- the page's Library
    and Results need `library`, its joe's mic capture and voice keys
    `microphone`, and its voice panel and transcript `transcripts` -- on
    loopback alone. A setting already in the environment is kept. With
    `--allow`, it serves what `backend` would: `--allow media` for the media
    API alone."""
    env = _api_env(allow, everything=allow is None)
    _disclaim()
    if allow is None:
        _echo("joe dev turns every capability on: name fewer with --allow, or run joe backend "
              "for the media API alone.")
    _echo("Starting Vite  -> http://localhost:3000/joe")
    _echo("Starting API   -> http://localhost:8000/api/health")
    _echo("Ctrl+C to stop both.\n")

    fe = subprocess.Popen([_npm, "run", "dev"])
    be = subprocess.Popen(_UVICORN, env=env)

    try:
        fe.wait()
        be.wait()
    except KeyboardInterrupt:
        _echo("\nShutting down...")
        _kill(fe)
        _kill(be)


# The performing family's demo contract: `serve` on the addresses given, and
# `check` a joe that is already up. Declared once for every member, in the qm
# corpus's ci/family-demo.yaml.

ROOT = Path(__file__).resolve().parent
BROWSER_PAGE = "walkthrough/03-in-the-browser.md"

# What `check` exits with when there is nothing to check against. Not 1: a
# server that is not answering, or a browser that will not start, says nothing
# about joe.
CANNOT_SAY = 3

# How long the API may take to answer before `serve` gives up. A cold start on
# Windows imports whisper and torch before uvicorn listens.
API_STARTUP = 120.0


def _answers(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            return 200 <= answer.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Address both servers bind."),
    port: int = typer.Option(..., "--port", help="Vite's port: the page is at /joe/."),
    api_port: int = typer.Option(..., "--api-port", help="The API's port."),
    state: Path = typer.Option(..., "--state", help="Scratch directory; see below."),
    qmcp_url: str = typer.Option(
        None, "--qmcp-url", help="Where the page's /v1 goes (QMCP_URL); unset keeps the default."),
    allow: Allow = None,
):
    """Start the API and Vite on the ports given, Vite once the API answers.

    `joe dev` with every address named: the API on --api-port without
    --reload, and Vite on --port with --strictPort and JOE_API_URL pointing at
    that API. The page answers only once the API does. Ctrl+C stops both.

    As with `joe dev`, the API serves every capability unless `--allow` names
    fewer: the page needs them, and a hub's cue needs `family`. joe has no
    authentication, so --host decides who that reaches (docs/security.md). The
    API is told to take requests from the page at --host and --port, as it
    takes them from `joe dev`'s on port 3000 (JOE_ALLOWED_ORIGINS).

    Recordings, the pipeline's output and the voice datapoints stay in this
    checkout's Data/, whatever --state says: the API resolves Data/ against its
    working directory and the pipeline and voice modules against the checkout,
    so the API runs from the checkout and STATE is only made.
    """
    node = shutil.which("node")
    vite = ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite.is_file():
        _echo("node and node_modules are needed: run `npm ci` first", err=True)
        raise typer.Exit(2)
    api_env = _api_env(allow, everything=allow is None)
    # Vite's proxy sends the page's requests on under the API's own Host with
    # the page's Origin, which the API refuses from any page it was not told of.
    api_env["JOE_ALLOWED_ORIGINS"] = ",".join(
        filter(None, [api_env.get("JOE_ALLOWED_ORIGINS"), f"http://{host}:{port}"]))
    state.mkdir(parents=True, exist_ok=True)
    api = f"http://{host}:{api_port}"
    _echo("joe has no authentication: whatever can reach the API's port is answered, with this "
          "account's rights.")
    _echo(f"API  -> {api}/api/health")
    be = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", host, "--port", str(api_port)],
        cwd=ROOT, env=api_env)
    started = time.monotonic()
    while not _answers(f"{api}/api/health"):
        if be.poll() is not None or time.monotonic() - started > API_STARTUP:
            _kill(be)
            _echo(f"the API did not answer at {api}/api/health", err=True)
            raise typer.Exit(1)
        time.sleep(0.25)
    env = {**os.environ, "JOE_API_URL": api}
    if qmcp_url:
        env["QMCP_URL"] = qmcp_url
    _echo(f"page -> http://{host}:{port}/joe/")
    fe = subprocess.Popen(
        [node, str(vite), "--host", host, "--port", str(port), "--strictPort"],
        cwd=ROOT, env=env)
    try:
        while fe.poll() is None and be.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _kill(fe)
        _kill(be)


@app.command()
def check(
    url: str = typer.Option(..., "--url", help="Where the page to check is served."),
    shots: Path = typer.Option(..., "--shots", help="Where the pictures are written."),
):
    """Run the walkthrough's browser page against the joe already serving URL.

    walkthrough/03-in-the-browser.md, attached through JOE_WALKTHROUGH_URL to
    the dev server at URL rather than starting servers of its own; it reaches
    the API through that server's proxy. Its pictures go to --shots. Exits with
    pytest's status, and with 3 when nothing answers at URL or Chromium will
    not start, because neither says anything about joe.
    """
    def cannot_say(why: str) -> None:
        _echo(f"check could not run: {why}", err=True)
        raise typer.Exit(CANNOT_SAY)

    if not _answers(url, timeout=5):
        cannot_say(f"nothing answers at {url}")
    # p5 comes from a CDN, and without it the page throws before it wires a
    # single control: a machine with no network would read as joe failing.
    page = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
    for script in re.findall(r'<script src="(https://[^"]+)"', page):
        if not _answers(script, timeout=10):
            cannot_say(f"the page loads {script} from the network, and it did not answer")
    # Python exits 1 when it cannot find a module, which is also the status of
    # a failed assertion: a broken pytest would read as joe failing.
    runner = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                            capture_output=True, text=True, check=False)
    if runner.returncode != 0:
        cannot_say(f"pytest does not run here: {(runner.stderr or runner.stdout).strip()[-200:]}")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as driver:
            driver.chromium.launch().close()
    except Exception as error:  # an import or a launch: either way, no browser
        cannot_say(f"Chromium would not start: {type(error).__name__}: {error}")
    shots = shots.resolve()
    shots.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "JOE_WALKTHROUGH_URL": url, "JOE_WALKTHROUGH_SHOTS": str(shots),
           "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", BROWSER_PAGE, "--doctest-glob=*.md",
         "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, check=False)
    raise typer.Exit(done.returncode)


@app.command()
def run(
    names: list[str] = typer.Argument(None, help="Recordings in Data/Audio/ to analyse, by file name.",
                                      show_default=False),
    every: bool = typer.Option(False, "--all", help="Analyse every recording in Data/Audio/."),
):
    """Run the audio processing pipeline once (Data/Audio/ -> Data/Output/): on the
    newest recording, those named, or every one with --all."""
    names = names or []
    if every and names:
        _echo("Name recordings or ask for --all, not both.", err=True)
        raise typer.Exit(2)
    _echo("Running pipeline...")
    result = subprocess.run([sys.executable, "main.py", *(["--all"] if every else names)], check=False)
    if result.returncode == 0:
        _echo("Done. Load results with `joe backend --allow library` + Fetch Latest.")
    else:
        _echo(f"Pipeline exited with code {result.returncode}.", err=True)
        raise typer.Exit(result.returncode)


@voice_app.command("devices")
def voice_devices():
    """List audio input devices this machine's backend can see."""
    from Modules.Voice import list_input_devices

    devices = list_input_devices()
    if not devices:
        _echo("No input devices found.")
        raise typer.Exit(1)

    # Host API in the line because the name is not unique: the same
    # microphone appears once per API, and a listing by name alone cannot be
    # chosen from.
    from Modules.Voice import saved_input_device

    saved = saved_input_device()
    width = max(len(d["name"]) for d in devices)
    for d in devices:
        mark = "S" if d["index"] == saved else ("*" if d["default"] else " ")
        _echo(
            f"{mark} [{d['index']:3d}] {d['name']:{width}s}  "
            f"{d['channels']}ch  {d['hostapi']}"
        )
    _echo()
    if saved is not None:
        _echo("S is the microphone `joe voice setup` saved; recording uses it.")
    _echo("* is this backend's default, which is not always a microphone.")
    _echo("`joe voice setup` finds and saves the one a voice arrives on.")


@voice_app.command("setup")
def voice_setup(
    seconds: float = typer.Option(1.5, help="Seconds to listen on each input"),
    confirm: bool = typer.Option(
        True, "--confirm/--no-confirm", help="Finish by transcribing a test sentence"
    ),
):
    """Find your microphone, save it, and prove it with a test sentence.

    Tries every input while you talk, keeps the microphone that heard you
    loudest -- on the most reliable host API it appears under -- and saves
    it so recording uses it from then on: no environment variable, and no
    restart of a running backend.
    """
    import time

    from Modules.Voice import (
        NoMicrophoneError,
        Voice,
        input_level,
        list_input_devices,
        rank_candidates,
        save_input_device,
    )

    devices = list_input_devices()
    if not devices:
        _echo("No input devices found. Is a microphone connected, and does the "
              "operating system see it?", err=True)
        raise typer.Exit(1)

    _echo(f"Finding your microphone among {len(devices)} inputs.")
    _echo(f"When the countdown ends, keep talking -- count slowly to thirty -- "
          f"for about {round(len(devices) * seconds)} seconds while each is tried.")
    for n in (3, 2, 1):
        _echo(f"  {n}...")
        time.sleep(1)
    _echo("  Talk now.")

    heard = []
    for i, d in enumerate(devices, 1):
        label = f"  [{i}/{len(devices)}] [{d['index']:3d}] {d['name']} ({d['hostapi']})"
        try:
            report = input_level(duration=seconds, device=d["index"])
        except NoMicrophoneError:
            _echo(f"{label}  unavailable")
            continue
        _echo(f"{label}  rms {report['rms']:.4f}  {'silent' if report['silent'] else 'heard'}")
        if not report["silent"]:
            heard.append((report["rms"], d))

    if not heard:
        _echo()
        _echo("No input heard you. Check that the microphone is not muted -- a "
              "hardware switch, or the operating system's own mute -- that desktop "
              "apps may use it (Windows: Settings > Privacy > Microphone), and "
              "keep talking through the whole sweep. Then run this again.", err=True)
        raise typer.Exit(1)

    candidates = rank_candidates(heard)

    def chosen(d, path):
        _echo()
        _echo(f"Your microphone: [{d['index']}] {d['name']} ({d['hostapi']}).")
        _echo(f"Saved to {path}. Recording uses it from now on.")

    if not confirm:
        chosen(candidates[0], save_input_device(candidates[0]))
        return

    # Nothing is saved until a device has recorded the sentence: the sweep
    # hearing a device is not proof that a recording can open it.
    _echo()
    _echo("Last check: say a short sentence now. Recording stops when you do. "
          "(The first run loads the speech model, which takes a moment.)")
    for d in candidates:
        try:
            result = Voice().listen(duration=10.0, device=d["index"], until_silence=True)
        except NoMicrophoneError as exc:
            _echo(f"  [{d['index']}] {d['name']} ({d['hostapi']}) could not record: {exc}")
            continue
        chosen(d, save_input_device(d))
        break
    else:
        _echo()
        _echo("No input that heard you could record. Nothing was saved. "
              "`joe voice devices` lists them; `joe voice listen --device N` "
              "tries one.", err=True)
        raise typer.Exit(1)

    text = result.get("text", "").strip()
    if result.get("speech_detected") is False or not text:
        _echo("Heard nothing that time. The microphone is saved; run `joe voice "
              "listen` to try again, or `joe voice setup` to choose again.", err=True)
        raise typer.Exit(1)
    _echo(f'Heard: "{text}"')
    _echo("If that is what you said, the voice loop will hear you.")


@voice_app.command("transcribe")
def voice_transcribe(
    path: str,
    model_size: str = "base",
    hint: str = typer.Option(None, help="Words the audio is expected to be, comma-separated"),
):
    """Transcribe an audio file to text."""
    from Modules.Voice import Voice

    result = Voice(model_size=model_size).transcribe(path, hint=hint)
    _echo(result["text"])


@voice_app.command("listen")
def voice_listen(
    duration: float = typer.Option(10.0, help="The most seconds to record"),
    model_size: str = "base",
    device: str = typer.Option(None, help="Input device index or name fragment"),
    until_silence: bool = typer.Option(
        True, "--until-silence/--fixed", help="Stop when the speaker stops, or record the full duration"
    ),
    hint: str = typer.Option(None, help="Words the answer is expected to be, comma-separated"),
):
    """Record from an input device and transcribe the result.

    Recording stops when you stop talking, up to `--duration`; `--fixed`
    records the whole duration. Without `--device`: `JOE_INPUT_DEVICE` if
    set, else the microphone `joe voice setup` saved, else the default.
    """
    from Modules.Voice import NoMicrophoneError, Voice

    if until_silence:
        _echo(f"Listening -- recording stops when you do (at most {duration:g}s)...")
    else:
        _echo(f"Listening for {duration:g}s...")
    try:
        result = Voice(model_size=model_size).listen(
            duration=duration, device=device, until_silence=until_silence, hint=hint
        )
    except NoMicrophoneError as exc:
        _echo(str(exc), err=True)
        raise typer.Exit(1)
    _echo(f"Saved: {result['audio_path']}")
    if result.get("speech_detected") is False:
        _echo("Heard no speech. `joe voice setup` checks which microphone hears you.", err=True)
        raise typer.Exit(1)
    _echo(result["text"])


@voice_app.command("level")
def voice_level(
    duration: float = 1.0,
    device: str = typer.Option(None, help="Input device index or name fragment"),
    every: bool = typer.Option(False, "--every", help="Try every input device in turn"),
):
    """How loud an input is right now. Records briefly, keeps nothing.

    `--every` walks the whole list, which is the fastest way to find which
    of several identically-named devices a voice actually arrives on: talk
    while it runs, and read the peaks.
    """
    from Modules.Voice import NoMicrophoneError, input_level, list_input_devices

    targets = [d["index"] for d in list_input_devices()] if every else [device]
    if every and not targets:
        _echo("No input devices found.", err=True)
        raise typer.Exit(1)

    heard = False
    for target in targets:
        try:
            report = input_level(duration=duration, device=target)
        except NoMicrophoneError as exc:
            if not every:
                _echo(str(exc), err=True)
                raise typer.Exit(1)
            _echo(f"  [{target}] unavailable: {exc}")
            continue
        mark = "  --  " if report["silent"] else " HEARD"
        heard = heard or not report["silent"]
        _echo(
            f"{mark} [{report['device']}] {report['name']}  "
            f"peak {report['peak']:.4f}  rms {report['rms']:.4f}"
        )

    if not heard:
        _echo()
        _echo("Nothing above silence. Say something while this runs, or the "
                   "device is muted.", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
