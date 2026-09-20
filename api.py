"""
Joe FastAPI server — exposes pipeline results and a trigger endpoint.

Endpoints:
    GET  /api/health                Health check
    GET  /api/results/latest        Returns the most-recent Process_Data JSON
    POST /api/run                   Runs the pipeline on Data/Audio/ (all files)
    POST /api/capture/start         Start backend sounddevice recording
    POST /api/capture/stop          Stop recording, flush WAV, return filename
    POST /api/audio/upload          Receive audio blob from browser, save to Data/Audio/
    GET  /api/audio/files           List saved audio files sorted by mtime
    GET  /api/audio/{filename}      Serve an audio file for browser playback
    POST /api/run/{filename}        Run the pipeline on a specific file in Data/Audio/

Run directly:
    python -m uvicorn api:app --reload --port 8000

Or via the CLI:
    uv run joe backend
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from capture import AudioCapture

app = FastAPI(title="Joe API", version="0.1.0")

# Allow the Vite dev server to call us directly (backup for when proxy isn't used)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("Data/Output")
AUDIO_DIR  = Path("Data/Audio")

# Locate main.py: try sibling of this file first (source tree), then fall back
# to CWD (works when api.py is an installed package and CWD is project root).
_HERE    = Path(__file__).parent
_MAIN_PY = (_HERE / "main.py") if (_HERE / "main.py").exists() else Path("main.py").resolve()
_PROJECT_ROOT = _MAIN_PY.parent
AUDIO_EXTENSIONS = {".wav", ".webm", ".mp3", ".ogg", ".flac"}
MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}

_capture = AudioCapture()


# ─── Existing endpoints ───────────────────────────────────────────────────────

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
    Runs the pipeline on all files in Data/Audio/ and returns stdout/stderr.
    Blocks until the pipeline completes.
    """
    # Strip any inherited JOE_AUDIO_FILE so the all-files route is never
    # accidentally scoped to a single file from a previous request.
    env = {k: v for k, v in os.environ.items() if k != "JOE_AUDIO_FILE"}
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_MAIN_PY),
            env=env,
            cwd=str(_PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return {"returncode": -1, "stdout": "", "stderr": "Pipeline timeout (120 s)"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"Pipeline error: {exc}"}
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


# ─── Backend capture ──────────────────────────────────────────────────────────

@app.post("/api/capture/start")
def capture_start():
    """Start recording from the default audio input device to Data/Audio/."""
    if _capture.is_recording:
        raise HTTPException(status_code=400, detail="Already recording")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{ts}.wav"
    _capture.start(filename)
    return {"status": "recording", "filename": filename}


@app.post("/api/capture/stop")
def capture_stop():
    """Stop the active backend recording and flush the WAV file."""
    if not _capture.is_recording:
        raise HTTPException(status_code=400, detail="Not recording")
    filename = _capture.stop()
    return {"status": "stopped", "filename": filename}


# ─── Audio file management ────────────────────────────────────────────────────

_UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
_UPLOAD_MIME_TO_EXT = {
    "audio/wav":  "wav",
    "audio/wave": "wav",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/ogg":  "ogg",
    "audio/flac": "flac",
}

@app.post("/api/audio/upload")
async def audio_upload(request: Request):
    """
    Receive a raw audio blob from the browser and save it to Data/Audio/.
    Content-Type must be one of the allowed audio MIME types.
    Limited to 100 MB; uses a microsecond timestamp to avoid collisions.
    """
    body = await request.body()
    if len(body) > _UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")

    raw_ct = request.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _UPLOAD_MIME_TO_EXT.get(raw_ct)
    if ext is None:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{raw_ct}'. Allowed: {', '.join(_UPLOAD_MIME_TO_EXT)}"
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"capture_{ts}.{ext}"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIO_DIR / filename).write_bytes(body)
    return {"filename": filename}


@app.get("/api/audio/files")
def audio_files():
    """List all audio files in Data/Audio/, sorted by modification time (newest first)."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (f for f in AUDIO_DIR.iterdir() if f.is_file() and f.suffix in AUDIO_EXTENSIONS),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return [
        {"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime}
        for f in files
    ]


def _audio_file(filename: str) -> Path:
    """
    Map a client-supplied name to a file inside AUDIO_DIR.

    Only a bare filename is accepted: no path separators, no parent or
    drive components, and the resolved candidate must stay inside
    AUDIO_DIR (which also rules out symlinks pointing elsewhere). Any
    rejection is reported as 404, identical to a missing file, so the
    response never reveals whether something exists outside the directory.
    """
    not_found = HTTPException(status_code=404, detail="File not found")
    if (
        not filename
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
        or Path(filename).name != filename
    ):
        raise not_found
    audio_root = AUDIO_DIR.resolve()
    try:
        candidate = (audio_root / filename).resolve()
    except (OSError, RuntimeError):
        raise not_found from None
    if not candidate.is_relative_to(audio_root) or not candidate.is_file():
        raise not_found
    return candidate


@app.get("/api/audio/{filename}")
def audio_serve(filename: str):
    """Serve an audio file from Data/Audio/ for browser playback."""
    path = _audio_file(filename)
    media_type = MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)


PIPELINE_EXTENSIONS = {".wav", ".webm", ".mp3", ".ogg", ".flac"}

@app.post("/api/run/{filename}")
async def run_on_file(filename: str):
    """
    Run the pipeline on a specific file in Data/Audio/.
    Sets JOE_AUDIO_FILE env var so main.py processes only that file.
    """
    path = _audio_file(filename)
    if path.suffix.lower() not in PIPELINE_EXTENSIONS:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": (
                f"Format '{path.suffix}' is not supported by the pipeline. "
                f"Supported: {', '.join(sorted(PIPELINE_EXTENSIONS))} "
                f"(WebM requires ffmpeg on PATH)"
            ),
        }
    env = {**os.environ, "JOE_AUDIO_FILE": str(path)}
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_MAIN_PY),
            env=env,
            cwd=str(_PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return {"returncode": -1, "stdout": "", "stderr": "Pipeline timeout (120 s)"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"Pipeline error: {exc}"}
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }
