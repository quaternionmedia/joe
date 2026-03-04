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

app = typer.Typer(
    help="Joe Audio Workbench - dev CLI",
    no_args_is_help=True,
)

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
    typer.echo("Starting Vite  -> http://localhost:3000/joe")
    typer.echo("Starting API   -> http://localhost:8000/api/health")
    typer.echo("Ctrl+C to stop both.\n")

    fe = subprocess.Popen([_npm, "run", "dev"])
    be = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--reload", "--port", "8000"]
    )

    try:
        fe.wait()
        be.wait()
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
        fe.terminate()
        be.terminate()
        fe.wait()
        be.wait()


@app.command()
def run():
    """Run the audio processing pipeline once (Data/Audio/ -> Data/Output/)."""
    typer.echo("Running pipeline...")
    result = subprocess.run([sys.executable, "main.py"], check=False)
    if result.returncode == 0:
        typer.echo("Done. Load results with `joe backend` + Fetch Latest.")
    else:
        typer.echo(f"Pipeline exited with code {result.returncode}.", err=True)
        raise typer.Exit(result.returncode)


if __name__ == "__main__":
    app()
