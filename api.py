"""
Joe FastAPI server — exposes pipeline results and a trigger endpoint.

Endpoints:
    GET  /api/health           Health check
    GET  /api/results/latest   Returns the most-recent Process_Data JSON
    POST /api/run              Runs python main.py as a subprocess

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
