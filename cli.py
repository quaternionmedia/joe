"""
Joe CLI - dev launcher for the Joe Audio Workbench.

Usage (with uv):
    uv run joe frontend   # Vite dev server only  (localhost:3000)
    uv run joe backend    # FastAPI server only    (localhost:8000)
    uv run joe dev        # Both servers together
    uv run joe run        # Run the pipeline once  (Data/Audio/ -> Data/Output/)

After `uv tool install -e .` the bare `joe` command works everywhere.
"""

import subprocess
import sys

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

app = typer.Typer(
    help="Joe Audio Workbench - dev CLI",
    no_args_is_help=True,
)

voice_app = typer.Typer(help="Speech analysis: transcription and mic capture.", no_args_is_help=True)
app.add_typer(voice_app, name="voice")

# npm is 'npm.cmd' on Windows when not in a shell
_npm = "npm.cmd" if sys.platform == "win32" else "npm"


@app.command()
def frontend():
    """Start the Vite frontend dev server (localhost:3000)."""
    subprocess.run([_npm, "run", "dev"], check=False)


@app.command()
def backend():
    """Start the FastAPI backend API server (localhost:8000)."""
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "api:app", "--reload", "--port", "8000"],
        check=False,
    )


@app.command()
def dev():
    """Start both frontend and backend dev servers. Ctrl+C stops both."""
    _echo("Starting Vite  -> http://localhost:3000/joe")
    _echo("Starting API   -> http://localhost:8000/api/health")
    _echo("Ctrl+C to stop both.\n")

    fe = subprocess.Popen([_npm, "run", "dev"])
    be = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--reload", "--port", "8000"]
    )

    try:
        fe.wait()
        be.wait()
    except KeyboardInterrupt:
        _echo("\nShutting down...")
        _kill(fe)
        _kill(be)


@app.command()
def run():
    """Run the audio processing pipeline once (Data/Audio/ -> Data/Output/)."""
    _echo("Running pipeline...")
    result = subprocess.run([sys.executable, "main.py"], check=False)
    if result.returncode == 0:
        _echo("Done. Load results with `joe backend` + Fetch Latest.")
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
    # microphone appears once per API, and a list you cannot choose from is
    # not a list.
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
