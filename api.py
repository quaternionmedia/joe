"""
Joe FastAPI server — exposes pipeline results and a trigger endpoint.

Endpoints. Each but the health check and the vocabulary belongs to the
capability in brackets, and answers 403 while it is off; a fresh joe has only
[media] on (Modules/Access.py, docs/security.md):
    GET  /api/health                Health check, and which capabilities are on
    GET  /api/results/latest        Returns the most-recent Process_Data JSON  [library]
    POST /api/run                   Runs the pipeline on Data/Audio/ (all files)  [library]
    POST /api/capture/start         Start backend sounddevice recording  [microphone]
    POST /api/capture/stop          Stop recording, flush WAV, return filename  [microphone]
    POST /api/audio/upload          Receive audio blob from browser, save to Data/Audio/  [library]
    GET  /api/audio/files           List saved audio files sorted by mtime  [library]
    GET  /api/audio/{filename}      Serve an audio file for browser playback  [library]
    POST /api/run/{filename}        Run the pipeline on a specific file in Data/Audio/  [library]
    GET  /api/voice/devices         Lists the server's audio input devices  [microphone]
    POST /api/voice/transcribe      Transcribes an audio file under Data/Audio/ or Data/Voice/  [library]
    POST /api/voice/listen          Records from an input device and transcribes it  [microphone]
    POST /api/voice/level           How loud one input device is right now  [microphone]
    GET  /api/voice/conversation    The conversation's states as they happen (server-sent events)  [transcripts]
    GET  /api/voice/conversation/state  The current state and recent events, once  [transcripts]
    POST /api/voice/conversation    A dialog's own state: speaking, recorded, gave_up, idle  [microphone]
    POST /api/voice/answer          An answer given by key or button, as if said  [microphone]
    POST /api/voice/hold            A held key: the turn stays open until it is released  [microphone]
    GET  /api/voice/control         Whether a key is held, an answer is waiting, and the question is interrupted  [microphone]
    POST /api/voice/watch           Opens a take while a question is still being asked  [microphone]
    POST /api/voice/unwatch         Closes a watch that will not be listened to  [microphone]
    GET  /api/voice/vocabulary      joe's own spoken words, and what each does
    GET  /api/voice/history         The whole transcript: every take heard and every sentence said  [transcripts]
    POST /api/voice/strike          Strike or restore a word of the take being transcribed  [microphone]
    GET  /api/voice/transcript      The take being transcribed, or the last one, once  [transcripts]
    GET  /api/media/capabilities    What the media API takes and does (docs/media.md)  [media]
    POST /api/media                 Takes audio or video and keeps its sound for a while  [media]
    POST /api/media/{id}/transcribe What is said in an upload, with segment and word times  [media]
    POST /api/media/{id}/analyze    Tempo, beats, onsets, loudness, silences and peaks of an upload  [media]
    DELETE /api/media/{id}          Removes an upload now  [media]

Run directly, with JOE_ALLOW_<NAME>=1 in the environment for each capability
to turn on:
    python -m uvicorn api:app --reload --port 8000

Or via the CLI:
    uv run joe backend
"""

import asyncio
import functools
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect

from capture import AudioCapture

from Modules import Access, Analysis, Cue, Media
from Modules.Control import Control
from Modules.Transcript import Datapoints, LiveTranscript
from Modules.Conversation import POSTED, Conversation
from Modules.Voice import STALL_SECONDS, NoMicrophoneError, Voice, input_level, list_input_devices
from Modules.Watch import Unwatched, Watch


@asynccontextmanager
async def _lifespan(_app):
    """As the server starts, it says that it has no authentication and what it
    lets callers do, with a warning for each capability turned on -- or, on a
    setting it cannot read, says which and does not start (`Modules.Access`).

    While it runs, uploaded media is swept as it expires -- even when nothing
    is being asked of it (`_sweep_media`)."""
    problems = Access.problems()
    for problem in problems:
        print(f"joe: {problem}", file=sys.stderr, flush=True)
    if problems:
        raise RuntimeError("joe will not start on a setting it cannot read (above)")
    for line in Access.banner():
        print(line, file=sys.stderr, flush=True)
    stop = threading.Event()
    threading.Thread(target=_sweep_media, args=(stop,), name="joe-media-sweep", daemon=True).start()
    try:
        yield
    finally:
        stop.set()


app = FastAPI(title="Joe API", version="0.1.0", lifespan=_lifespan)

# Pages joe takes requests from may read its answers: the Vite dev page calling
# the API directly (a backup for when its proxy is not used), and any page in
# JOE_ALLOWED_ORIGINS.
app.add_middleware(Access.PageCORS, allow_methods=["GET", "POST"], allow_headers=["*"])
# Outermost: a request a browser was made to send from another site, or under a
# name joe does not answer to, is refused before anything else sees it.
app.add_middleware(Access.Guard)

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


def _needs(capability: str) -> list:
    """A route's dependency on one capability: a 403 naming its setting while
    it is off, judged before anything the route was asked."""

    async def allowed() -> None:
        if not Access.allowed(capability):
            raise HTTPException(status_code=403, detail=Access.refusal(capability))

    allowed.capability = capability
    return [Depends(allowed)]


MEDIA, MICROPHONE, TRANSCRIPTS, LIBRARY = (
    _needs(name) for name in ("media", "microphone", "transcripts", "library"))

# The one conversation this process has: its microphone is the only one.
conversation = Conversation()
control = Control()
datapoints = Datapoints()
# The take being transcribed, or the last one; and the last take that had
# speech, which a dialog's outcome is recorded against.
transcript: LiveTranscript | None = None
last_take: str | None = None
# The take opened over the question being asked, if any: one at a time.
watching: Watch | None = None
_watch_lock = threading.Lock()
# The most answers a question can offer as controls: one per number key.
MAX_OPTIONS = 9
ANSWER_CHARS = 100


# ─── Existing endpoints ───────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Returns ok when the server is running, and which capabilities are on."""
    return {"status": "ok", "allowed": Access.allowed_map()}


@app.get("/api/results/latest", dependencies=LIBRARY)
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


@app.post("/api/run", dependencies=LIBRARY)
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

@app.post("/api/capture/start", dependencies=MICROPHONE)
def capture_start():
    """Start recording from the default audio input device to Data/Audio/."""
    if _capture.is_recording:
        raise HTTPException(status_code=400, detail="Already recording")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{ts}.wav"
    _capture.start(filename)
    return {"status": "recording", "filename": filename}


@app.post("/api/capture/stop", dependencies=MICROPHONE)
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

@app.post("/api/audio/upload", dependencies=LIBRARY)
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


@app.get("/api/audio/files", dependencies=LIBRARY)
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


def _is_bare_filename(filename: str) -> bool:
    """Whether a client-supplied name is a plain filename and nothing else.

    No path separators, no parent or drive components, no NUL byte (it
    reaches the filesystem call and raises out of the handler), and no
    trailing dot or space (Windows strips those when opening, so `x.wav.`
    and `"x.wav "` open the file they alias under a name no listing shows).

    Shared by every route that takes a name, because the two that existed
    did not agree: `/api/audio/{filename}` refused all of this and
    `/api/voice/transcribe` refused none of it, so one name was 404 on the
    first and 200 on the second.
    """
    return not (
        not filename
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or filename.rstrip(". ") != filename
        or Path(filename).name != filename
    )


def _audio_file(filename: str) -> Path:
    """
    Map a client-supplied name to a file inside AUDIO_DIR.

    Only a bare filename is accepted (see `_is_bare_filename`), and the
    resolved candidate must stay inside AUDIO_DIR (which also rules out
    symlinks pointing elsewhere). Any rejection is reported as 404,
    identical to a missing file, so the response never reveals whether
    something exists outside the directory.
    """
    not_found = HTTPException(status_code=404, detail="File not found")
    if not _is_bare_filename(filename):
        raise not_found
    audio_root = AUDIO_DIR.resolve()
    try:
        candidate = (audio_root / filename).resolve()
    except (OSError, RuntimeError):
        raise not_found from None
    if not candidate.is_relative_to(audio_root) or not candidate.is_file():
        raise not_found
    return candidate


@app.get("/api/audio/{filename}", dependencies=LIBRARY)
def audio_serve(filename: str):
    """Serve an audio file from Data/Audio/ for browser playback."""
    path = _audio_file(filename)
    media_type = MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)


PIPELINE_EXTENSIONS = {".wav", ".webm", ".mp3", ".ogg", ".flac"}

@app.post("/api/run/{filename}", dependencies=LIBRARY)
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


def _resolve_audio_path(filename: str) -> Path:
    """Resolve `filename` to a real file under Data/Audio/ or Data/Voice/.

    Holds the name to the same rule as `/api/audio/{filename}`: a bare
    filename, resolving inside one of the two directories. This is reachable
    from an HTTP request, and an alias accepted here transcribes a file the
    library never lists.
    """
    not_found = HTTPException(
        status_code=404,
        detail=f"No such file under Data/Audio/ or Data/Voice/: {filename}",
    )
    if not _is_bare_filename(filename):
        raise not_found
    for base in (Path("Data/Audio"), Path("Data/Voice")):
        try:
            candidate = (base / filename).resolve()
        except (OSError, RuntimeError):
            raise not_found from None
        if candidate.is_relative_to(base.resolve()) and candidate.is_file():
            return candidate
    raise not_found


@app.get("/api/voice/devices", dependencies=MICROPHONE)
def voice_devices():
    """Audio input devices the server's machine can see, and which one is default.

    Query this before relying on `/api/voice/listen` — it is the server's
    hardware that records, not the caller's, so "is there a microphone" is a
    question about wherever this process is running.
    """
    devices = list_input_devices()
    return {
        "devices": devices,
        "microphone_available": any(d["default"] for d in devices) or bool(devices),
    }


@app.post("/api/voice/transcribe", dependencies=LIBRARY)
def voice_transcribe(filename: str):
    """Transcribes an audio file already present under Data/Audio/ or Data/Voice/."""
    path = _resolve_audio_path(filename)
    voice = Voice()
    return voice.transcribe(str(path))


@app.post("/api/voice/listen", dependencies=MICROPHONE)
def voice_listen(
    duration: float = 5.0,
    device: str | None = None,
    until_silence: bool = True,
    silence_ms: int = 800,
    hint: str | None = None,
):
    """Records from an input device and transcribes it.

    This is the human-facing seam, so the polite default lives here:
    `duration` is the cap, and the recording ends `silence_ms` after the
    speaker stops — a fixed window truncates a slow answer and keeps
    recording after a quick one. `until_silence=false` restores the
    exact-length window.

    `device` is an index or a name fragment; omitted, the server's default
    input is used, or `JOE_INPUT_DEVICE` if that is set.

    `hint` is the words a short answer is expected to be, comma-separated --
    "approve, hold" -- handed to the transcriber as its prompt. It biases and
    never constrains: what was heard is what comes back.

    A take `/api/voice/watch` opened, that someone began by speaking over the
    question or holding the talk key, is this take: it is returned when it
    ends, from its first word. One nobody began is closed, and this take is
    recorded afresh.
    """
    _bounds(duration, silence_ms, hint)
    adopted = _adopt_watch()
    if adopted is not None:
        adopted.finished.wait()
        control.quiet()
        if adopted.error is not None:
            raise adopted.error
        return adopted.result
    return _listen_once(duration, device, until_silence, silence_ms, hint)


def _bounds(duration: float, silence_ms: int, hint: str | None) -> None:
    if not 0 < duration <= 60:
        raise HTTPException(status_code=400, detail="duration must be between 0 and 60 seconds")
    if not 100 <= silence_ms <= 5000:
        raise HTTPException(status_code=400, detail="silence_ms must be between 100 and 5000")
    if hint is not None and len(hint) > 500:
        raise HTTPException(status_code=400, detail="hint must be at most 500 characters")


def _listen_once(duration: float, device: str | None, until_silence: bool, silence_ms: int,
                 hint: str | None, watch: Watch | None = None) -> dict:
    """One take, recorded and transcribed: the listen route's, or a watch's."""
    global transcript, last_take
    voice = Voice()
    live = LiveTranscript(
        transcribe=lambda samples, prompt: voice.transcribe_samples(samples, hint=hint, prompt=prompt),
        hint=hint,
        publish=lambda **event: conversation.publish("transcript", **event),
        datapoints=datapoints,
        previous=last_take,
        notify=lambda state, **detail: conversation.publish(state, **detail),
    )
    if watch is None:
        transcript = live
        on_event = _report
        # A question was just asked: the cue to speak, finished before the
        # microphone opens so it is never recorded -- unless the answer was
        # already given by key, and the turn is over before it began.
        if conversation.snapshot()["state"] == "speaking" and not control.snapshot()["answer_waiting"]:
            Cue.play("turn", settle=True)
    else:
        def shown() -> None:
            global transcript
            transcript = live

        watch.on_begin = shown

        def on_event(state: str, **detail) -> None:
            # Over the question, nothing is published until someone begins.
            if state == "level" or watch.begun.is_set():
                _report(state, **detail)
    try:
        result = voice.listen(
            duration=duration,
            device=device,
            until_silence=until_silence,
            silence_after=silence_ms / 1000,
            on_event=on_event,
            hint=hint,
            control=control,
            live=live,
            watch=watch,
        )
        if result.get("source") == "key":
            Cue.play("heard")
        if result.get("take") or result.get("source") == "key":
            last_take = result.get("take") or live.take
            datapoints.write("take", take=last_take, audio=result.get("audio_path") or None,
                             source=result.get("source", "voice"), hint=hint,
                             text=result.get("text", ""), confidence=result.get("confidence"),
                             segments=len(live.segments),
                             struck={s.index: sorted(s.struck) for s in live.segments if s.struck},
                             over_question=watch is not None)
        return result
    except NoMicrophoneError as exc:
        if watch is None:
            conversation.publish("idle", text=f"The microphone could not record: {exc}")
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/voice/watch", dependencies=MICROPHONE)
def voice_watch(
    duration: float = 5.0,
    device: str | None = None,
    until_silence: bool = True,
    silence_ms: int = 800,
    hint: str | None = None,
):
    """Opens a take while a question is still being asked, so a person who
    answers over it is heard from their first word.

    Takes `/api/voice/listen`'s parameters and returns at once. Until someone
    begins -- speech louder than the question's own echo, or the talk key
    held -- nothing is published and nothing counts toward the cap; once they
    have, `/api/voice/control` reports `interrupted`, so the question can
    stop, and the next listen returns the take. A new watch closes the last.
    `JOE_BARGE_IN=0` leaves only the keys to interrupt (`Modules.Watch`).
    """
    global watching
    _bounds(duration, silence_ms, hint)
    _close_watch()
    control.quiet()
    watch = Watch(control=control)

    def record() -> None:
        try:
            watch.result = _listen_once(duration, device, until_silence, silence_ms, hint, watch=watch)
        except Unwatched:
            pass
        except Exception as exc:  # noqa: BLE001 -- the listen that comes for it raises it
            watch.error = exc
        finally:
            watch.finished.set()

    with _watch_lock:
        watching = watch
    threading.Thread(target=record, name="joe-watch", daemon=True).start()
    return {"watching": True, "voice": watch.voice}


@app.post("/api/voice/unwatch", dependencies=MICROPHONE)
def voice_unwatch():
    """Closes a watch that will not be listened to, begun or not."""
    _close_watch()
    control.quiet()
    return {"watching": False}


def _take_watch() -> Watch | None:
    global watching
    with _watch_lock:
        watch, watching = watching, None
    return watch


def _close_watch() -> None:
    watch = _take_watch()
    if watch is not None:
        watch.close()
        watch.finished.wait(timeout=STALL_SECONDS + 1)


def _adopt_watch() -> Watch | None:
    """The open watch when someone began it; otherwise None, with any watch
    closed and its microphone released for the take that replaces it."""
    watch = _take_watch()
    if watch is None:
        return None
    if watch.adopt():
        return watch
    watch.finished.wait(timeout=STALL_SECONDS + 1)
    return None


def _report(state: str, **detail) -> None:
    """The listen route's watcher: levels to the level, states to the log, and
    the heard cue once a take with speech has closed."""
    if state == "level":
        conversation.level(detail.get("rms", 0.0), detail.get("threshold"))
    else:
        conversation.publish(state, **detail)
        if state == "transcribing":
            Cue.play("heard")


@app.post("/api/voice/answer", dependencies=MICROPHONE)
async def voice_answer(request: Request):
    """An answer given without speaking -- a key or a button -- taken as if said.

    Body: `{"text": "approve"}`. The take in progress ends at once and returns
    it; with none in progress, the next take returns it without opening the
    microphone, if it starts within `Modules.Control.ANSWER_SECONDS`.
    """
    body = await _json_body(request)
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip() or len(text) > ANSWER_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"text must be a word or phrase of at most {ANSWER_CHARS} characters")
    control.answer(text.strip())
    return control.snapshot()


@app.post("/api/voice/hold", dependencies=MICROPHONE)
async def voice_hold(request: Request):
    """A held key. Body: `{"held": true}` when pressed, `{"held": false}` when
    released. While held, a take does not end on a pause or at its cap; the
    release ends it."""
    body = await _json_body(request)
    held = body.get("held") if isinstance(body, dict) else None
    if not isinstance(held, bool):
        raise HTTPException(status_code=400, detail="held must be true or false")
    control.hold(held)
    return control.snapshot()


@app.get("/api/voice/control", dependencies=MICROPHONE)
def voice_control():
    """Whether a key is held, whether an answer is waiting for a take, and
    whether the question being said is interrupted -- by either of those, or
    by speech over it that a watch heard."""
    return control.snapshot()


@app.get("/api/voice/history", dependencies=TRANSCRIPTS)
def voice_history(limit: int = 200):
    """The whole transcript, oldest first: every take joe heard, with its
    segments, what was struck and how it was labelled, and every sentence the
    program asking said -- read from the datapoints, so the page keeps it
    across a reload. `kept` is false when `JOE_DATAPOINTS=0` keeps none."""
    if not 1 <= limit <= 2000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 2000")
    from Modules import History

    return {"entries": History.read(datapoints.manifest, limit), "kept": datapoints.enabled}


@app.get("/api/voice/vocabulary")
def voice_vocabulary():
    """joe's own spoken words -- what a segment saying each does -- for the
    page to show beside what the program asking listens for."""
    from Modules import Vocabulary

    return {"phrases": Vocabulary.entries()}


@app.get("/api/voice/transcript", dependencies=TRANSCRIPTS)
def voice_transcript():
    """The take being transcribed, or the last one: its segments, the words
    struck, and the text so far."""
    if transcript is None:
        return {"take": None, "segments": [], "text": ""}
    return transcript.snapshot()


@app.post("/api/voice/strike", dependencies=MICROPHONE)
async def voice_strike(request: Request):
    """Strike a word of the take being transcribed, or restore a struck one.

    Body: `{"take": "...", "segment": 0, "word": 2}`, or `{"take": "...",
    "last": true}` for the last word still standing. The take's text leaves
    struck words out. `409` for a take that is not the current one.
    """
    body = await _json_body(request)
    if not isinstance(body, dict) or not isinstance(body.get("take"), str):
        raise HTTPException(status_code=400, detail="take must name the take")
    if transcript is None or body["take"] != transcript.take:
        raise HTTPException(status_code=409, detail="that take is no longer being transcribed")
    if body.get("last") is True:
        transcript.strike_last()
    else:
        segment, word = body.get("segment"), body.get("word")
        if not isinstance(segment, int) or not isinstance(word, int):
            raise HTTPException(status_code=400, detail="segment and word must be numbers, or last true")
        try:
            transcript.strike(segment, word)
        except IndexError:
            raise HTTPException(status_code=404, detail="no such word in that take")
    return transcript.snapshot()


async def _json_body(request: Request):
    """The request's JSON body: 415 for one not sent as JSON, 400 for one that
    is not JSON. A form, or text/plain holding JSON, is what a page on another
    site can make a browser send without asking first (docs/security.md)."""
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind != "application/json" and not kind.endswith("+json"):
        raise HTTPException(status_code=415,
                            detail="the body must be JSON, sent as Content-Type: application/json")
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")


@app.get("/api/voice/conversation/state", dependencies=TRANSCRIPTS)
def voice_conversation_state():
    """The current state, the recent events, and the microphone level, once."""
    return conversation.snapshot()


@app.post("/api/voice/conversation", dependencies=MICROPHONE)
async def voice_conversation_post(request: Request):
    """A dialog's own state, posted by the program asking the question.

    Body: `{"state": ..., "text": ..., "reason": ...}`. Only the dialog's
    states are accepted (`speaking`, `recorded`, `gave_up`, `idle`); the
    microphone's are joe's to report.
    """
    body = await _json_body(request)
    state = body.get("state") if isinstance(body, dict) else None
    if state not in POSTED:
        raise HTTPException(
            status_code=400,
            detail=f"state must be one of {', '.join(POSTED)}; the others are the microphone's",
        )
    detail = {k: str(v) for k, v in body.items() if k in ("reason",) and v is not None}
    options = body.get("options")
    if options is not None:
        if (state != "speaking" or not isinstance(options, list) or len(options) > MAX_OPTIONS
                or not all(isinstance(o, str) and o.strip() for o in options)):
            raise HTTPException(
                status_code=400,
                detail=f"options go on a speaking state, as at most {MAX_OPTIONS} non-empty strings",
            )
        detail["options"] = [o.strip() for o in options]
    event = conversation.publish(state, text=str(body.get("text") or ""), **detail)
    # What the program asking said, so the transcript read back holds both sides.
    if state == "speaking" and event["text"]:
        datapoints.write("said", text=event["text"], reason=detail.get("reason"),
                         options=detail.get("options"))
    # What the dialog made of the last take: the label a later pass tunes against.
    if state in ("recorded", "gave_up") and last_take:
        datapoints.write("outcome", take=last_take, state=state, text=event["text"])
    return event


async def _conversation_events(request: Request, poll: float = 0.05):
    """Server-sent events: every kept event after the client's last, then each
    new one as it happens, with the level as its own event type."""
    try:
        last = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        last = 0
    level_seq = -1
    while not await request.is_disconnected():
        for event in conversation.since(last):
            last = event["seq"]
            yield f"id: {last}\ndata: {json.dumps(event)}\n\n"
        level = conversation.current_level()
        if level["seq"] != level_seq:
            level_seq = level["seq"]
            yield f"event: level\ndata: {json.dumps(level)}\n\n"
        await asyncio.sleep(poll)


@app.get("/api/voice/conversation", dependencies=TRANSCRIPTS)
async def voice_conversation(request: Request):
    """The conversation's states as they happen, as server-sent events."""
    return StreamingResponse(
        _conversation_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/voice/level", dependencies=MICROPHONE)
def voice_level(duration: float = 1.0, device: str | None = None):
    """How loud one input device is right now. Records briefly, keeps nothing.

    This is the route for choosing between devices whose names do not
    distinguish them: speak, and the one that is not silent is the one to
    use.
    """
    if not 0 < duration <= 10:
        raise HTTPException(status_code=400, detail="duration must be between 0 and 10 seconds")
    try:
        return input_level(duration=duration, device=device)
    except NoMicrophoneError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ─── Media for the video pipeline ─────────────────────────────────────────────
#
# Audio or video uploaded once, then analysed -- and transcribed -- by id, for a
# video editor's captions and timeline. Every failure is `{"detail": str}`.
# docs/media.md is the reference; Modules/Media.py and Modules/Analysis.py are
# the work.

media_store = Media.MediaStore()

# Media work runs on threads of its own, never on the event loop nor on the
# pool FastAPI answers plain `def` routes with -- the voice API's among them, so
# a video editor's queue never keeps a conversation waiting. Transcriptions
# take turns on one thread, in the order they came (they share one whisper
# model); decoding uploads and analysing them, up to four at once.
_speech_work = ThreadPoolExecutor(max_workers=1, thread_name_prefix="joe-media-speech")
_media_work = ThreadPoolExecutor(max_workers=4, thread_name_prefix="joe-media")


async def _on(pool: ThreadPoolExecutor, work, /, *args, **kwargs):
    """`work(*args, **kwargs)` on `pool`, awaited."""
    return await asyncio.get_running_loop().run_in_executor(pool, functools.partial(work, *args, **kwargs))


def _sweep_media(stop: threading.Event) -> None:
    """Sweep expired uploads now and then until `stop`: a quarter of the TTL,
    at most a minute apart. A sweep that fails waits for the next."""
    while True:
        try:
            media_store.sweep()
        except Exception:  # noqa: BLE001 -- the next sweep tries again
            traceback.print_exc()
        if stop.wait(min(60.0, max(1.0, media_store.ttl / 4))):
            return


def _refusal(errors) -> str:
    """FastAPI's validation errors as one sentence: `where: what`, joined."""
    said = []
    for error in errors:
        where = ".".join(str(part) for part in tuple(error.get("loc", ()))[1:]) or "request"
        said.append(f"{where}: {error.get('msg', 'is not valid')}")
    return "; ".join(said) or "the request is not valid"


class _MediaRoute(APIRoute):
    """A media route answers every failure as `{"detail": str}`, V1's one error
    shape: a refused parameter as well, which FastAPI would answer with a list,
    a `Media.MediaError` with its own status, and anything unforeseen as a 500
    whose traceback goes to the server's log. Scoped to `/api/media`, so every
    other route answers as it always has."""

    def get_route_handler(self):
        handle = super().get_route_handler()

        async def route(request: Request):
            try:
                return await handle(request)
            except RequestValidationError as exc:
                raise HTTPException(status_code=422, detail=_refusal(exc.errors())) from None
            except Media.MediaError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
            except (StarletteHTTPException, ClientDisconnect):
                raise  # answered as it is; a client that left hears nothing
            except Exception as exc:  # noqa: BLE001 -- answered in V1's shape, and logged
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from None

        return route


media = APIRouter(prefix="/api/media", route_class=_MediaRoute, dependencies=MEDIA)


@media.get("/capabilities")
def media_capabilities():
    """What this engine takes and does, for a client to check before sending:
    `{"formats", "features", "speech_model", "word_timestamps", "max_bytes",
    "max_seconds", "ttl_seconds"}`. `formats` is empty when there is no ffmpeg,
    since then nothing can be taken."""
    return {
        "formats": sorted(Media.FORMATS) if Media.ffmpeg_path() else [],
        "features": list(Analysis.FEATURES),
        "speech_model": Media.speech_model(),
        # The locked openai-whisper has had word timestamps since 20230314.
        "word_timestamps": True,
        "max_bytes": Media.max_bytes(),
        "max_seconds": Media.max_seconds(),
        "ttl_seconds": float(media_store.ttl),
    }


@media.post("", status_code=201)
async def media_upload(request: Request):
    """Audio or video as the raw body, its type in `Content-Type`. Answers `201
    {"media_id", "duration", "sample_rate", "channels", "has_audio"}`.

    The headers are judged before a byte is read: 415 for a type joe does not
    take, 413 for a declared length over `JOE_MEDIA_MAX_BYTES`, 503 when there
    is no ffmpeg. The body is written to disk as it arrives and refused (413)
    the moment it passes the cap; ffmpeg's decode runs on the media threads.
    422 for a file with no decodable audio -- a video with no sound track
    among them -- and 413 for a sound longer than `JOE_MEDIA_MAX_SECONDS`.
    """
    content_type = request.headers.get("content-type")
    kind = Media.content_kind(content_type)
    if kind is None:
        given = (content_type or "").split(";")[0].strip().lower() or "none"
        raise HTTPException(
            status_code=415,
            detail=f"unsupported media type '{given}'; joe takes {', '.join(sorted(Media.FORMATS))}",
        )
    cap = Media.max_bytes()
    too_large = f"media larger than {cap} bytes (JOE_MEDIA_MAX_BYTES)"
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(status_code=413, detail=too_large)
    ffmpeg = Media.ffmpeg_path()
    if ffmpeg is None:
        raise HTTPException(status_code=503,
                            detail="ffmpeg was not found: set JOE_FFMPEG to its path or put it on PATH")
    await _on(_media_work, media_store.sweep)
    with media_store.receiving() as (media_id, folder):
        upload = folder / f"upload.{Media.FORMATS[kind]}"
        written = 0
        with open(upload, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > cap:
                    raise HTTPException(status_code=413, detail=too_large)
                out.write(chunk)
        try:
            sound = await _on(_media_work, Media.extract, upload, folder, ffmpeg)
        finally:
            upload.unlink(missing_ok=True)
        return media_store.commit(media_id, sound).answer()


# The analysis's answer, in V1's order: every key but `duration` is a feature's.
_ANALYSIS_KEYS = ("tempo", "beats", "onsets", "loudness", "silences", "peaks")


def _features(asked: str | None) -> list[str]:
    """`features`, comma-separated; absent or empty means all of them."""
    names = [name.strip().lower() for name in (asked or "").split(",") if name.strip()]
    if not names:
        return list(Analysis.FEATURES)
    unknown = [name for name in names if name not in Analysis.FEATURES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown feature '{unknown[0]}'; joe measures {', '.join(Analysis.FEATURES)}",
        )
    return names


@media.post("/{media_id}/analyze")
async def media_analyze(
    media_id: str,
    features: str | None = None,
    peaks_rate: int = Query(Analysis.DEFAULT_PEAKS_RATE, ge=1, le=1000),
    silence_db: float = Query(Analysis.DEFAULT_SILENCE_DB, ge=-120.0, le=0.0),
    silence_min: float = Query(Analysis.DEFAULT_SILENCE_MIN, gt=0.0, le=3600.0),
):
    """`{"duration", "tempo", "beats", "onsets", "loudness", "silences", "peaks"}`,
    with only the features asked for. Times are seconds of the uploaded media.

    `peaks_rate` is the waveform's values per second; `silence_db` and
    `silence_min` are the level a silence stays under and how long it lasts.
    Measured on the media threads.
    """
    wanted = _features(features)

    def analyze() -> dict:
        with media_store.use(media_id) as item:
            found = Analysis.analyze(
                item.sound, item.rhythm, wanted, peaks_rate=peaks_rate, silence_db=silence_db,
                silence_min=silence_min, ffmpeg=Media.ffmpeg_path(),
            )
        return {"duration": item.duration, **{key: found[key] for key in _ANALYSIS_KEYS if key in found}}

    return await _on(_media_work, analyze)


@media.post("/{media_id}/transcribe")
async def media_transcribe(media_id: str, language: str | None = None, words: bool = True):
    """`{"text", "language", "segments": [{"start", "end", "text", "words":
    [{"start", "end", "word", "probability"}]}], "info"}`, in seconds of the
    uploaded media.

    `language` is a code or a name; absent or empty, whisper detects it.
    `words=false` leaves every segment's `words` empty. Transcriptions take
    turns, in the order they came, on media's own thread and whisper model --
    never the voice loop's.
    """

    def transcribe() -> dict:
        with media_store.use(media_id) as item:
            return Media.transcribe(item, language=language, words=words)

    return await _on(_speech_work, transcribe)


@media.delete("/{media_id}", status_code=204)
def media_delete(media_id: str):
    """Removes an upload now -- or, if it is being transcribed or analysed, as
    soon as that ends. 404 for one that is not here."""
    media_store.delete(media_id)
    return Response(status_code=204)


app.include_router(media)
