"""
Joe FastAPI server — exposes pipeline results and a trigger endpoint.

Endpoints:
    GET  /api/health              Health check
    GET  /api/results/latest      Returns the most-recent Process_Data JSON
    POST /api/run                 Runs python main.py as a subprocess
    POST /api/voice/transcribe    Transcribes an audio file under Data/Audio/ or Data/Voice/
    POST /api/voice/listen        Records from the server's mic and transcribes it

Run directly:
    python -m uvicorn api:app --reload --port 8000

Or via the CLI:
    uv run joe backend
"""

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from Modules.Voice import Voice

app = FastAPI(title="Joe API", version="0.1.0")

# Allow the Vite dev server to call us directly (backup for when proxy isn't used)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("Data/Output")


@app.get("/api/health")
def health():
    """Returns ok when the server is running."""
    return {"status": "ok"}


@app.get("/api/results/latest")
def get_latest():
    """
    Returns the content of the most recently written Process_Data JSON file.
    Raises 404 if no output exists yet.
    """
    if not OUTPUT_DIR.exists():
        raise HTTPException(
            status_code=404,
            detail="No output directory found — drop an audio file in Data/Audio/ and run `joe run`",
        )

    files = sorted(
        OUTPUT_DIR.glob("**/Process_Data_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise HTTPException(
            status_code=404,
            detail="No results yet — run `joe run` first",
        )

    return json.loads(files[0].read_text(encoding="utf-8"))


@app.post("/api/run")
async def run_pipeline():
    """
    Runs python main.py as a subprocess and returns stdout/stderr.
    Blocks until the pipeline completes.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "main.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def _resolve_audio_path(filename: str) -> Path:
    """Resolve `filename` to a real file under Data/Audio/ or Data/Voice/.

    Rejects absolute paths and any path that escapes those two directories,
    since this is reachable from an HTTP request.
    """
    for base in (Path("Data/Audio"), Path("Data/Voice")):
        candidate = (base / filename).resolve()
        if candidate.is_relative_to(base.resolve()) and candidate.is_file():
            return candidate
    raise HTTPException(
        status_code=404,
        detail=f"No such file under Data/Audio/ or Data/Voice/: {filename}",
    )


@app.post("/api/voice/transcribe")
def voice_transcribe(filename: str):
    """Transcribes an audio file already present under Data/Audio/ or Data/Voice/."""
    path = _resolve_audio_path(filename)
    voice = Voice()
    return voice.transcribe(str(path))


@app.post("/api/voice/listen")
def voice_listen(duration: float = 5.0):
    """Records `duration` seconds from the server's default microphone and transcribes it."""
    if not 0 < duration <= 60:
        raise HTTPException(status_code=400, detail="duration must be between 0 and 60 seconds")
    voice = Voice()
    return voice.listen(duration=duration)
