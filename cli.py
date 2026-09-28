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
    width = max(len(d["name"]) for d in devices)
    for d in devices:
        mark = "*" if d["default"] else " "
        _echo(
            f"{mark} [{d['index']:3d}] {d['name']:{width}s}  "
            f"{d['channels']}ch  {d['hostapi']}"
        )
    _echo()
    _echo("* is this backend's default, which is not always a microphone.")
    _echo("`joe voice level --device N` says which one a voice arrives on.")


@voice_app.command("transcribe")
def voice_transcribe(path: str, model_size: str = "base"):
    """Transcribe an audio file to text."""
    from Modules.Voice import Voice

    result = Voice(model_size=model_size).transcribe(path)
    _echo(result["text"])


@voice_app.command("listen")
def voice_listen(
    duration: float = 5.0,
    model_size: str = "base",
    device: str = typer.Option(None, help="Input device index or name fragment"),
):
    """Record from an input device and transcribe the result.

    Without `--device`, the backend's default is used, or `JOE_INPUT_DEVICE`
    if it is set.
    """
    from Modules.Voice import NoMicrophoneError, Voice

    _echo(f"Listening for {duration}s...")
    try:
        result = Voice(model_size=model_size).listen(duration=duration, device=device)
    except NoMicrophoneError as exc:
        _echo(str(exc), err=True)
        raise typer.Exit(1)
    _echo(f"Saved: {result['audio_path']}")
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
