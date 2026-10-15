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
    GET  /api/voice/devices         Lists the server's audio input devices
    POST /api/voice/transcribe      Transcribes an audio file under Data/Audio/ or Data/Voice/
    POST /api/voice/listen          Records from an input device and transcribes it
    POST /api/voice/level           How loud one input device is right now
    GET  /api/voice/conversation    The conversation's states as they happen (server-sent events)
    GET  /api/voice/conversation/state  The current state and recent events, once
    POST /api/voice/conversation    A dialog's own state: speaking, recorded, gave_up, idle
    POST /api/voice/answer          An answer given by key or button, as if said
    POST /api/voice/hold            A held key: the turn stays open until it is released
    GET  /api/voice/control         Whether a key is held, an answer is waiting, and the question is interrupted
    POST /api/voice/watch           Opens a take while a question is still being asked
    POST /api/voice/unwatch         Closes a watch that will not be listened to
    GET  /api/voice/vocabulary      joe's own spoken words, and what each does
    GET  /api/voice/history         The whole transcript: every take heard and every sentence said
    POST /api/voice/strike          Strike or restore a word of the take being transcribed
    GET  /api/voice/transcript      The take being transcribed, or the last one, once

Run directly:
    python -m uvicorn api:app --reload --port 8000

Or via the CLI:
    uv run joe backend
"""

import asyncio
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from capture import AudioCapture

from Modules import Cue
from Modules.Control import Control
from Modules.Transcript import Datapoints, LiveTranscript
from Modules.Conversation import POSTED, Conversation
from Modules.Voice import STALL_SECONDS, NoMicrophoneError, Voice, input_level, list_input_devices
from Modules.Watch import Unwatched, Watch

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


@app.get("/api/voice/devices")
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


@app.post("/api/voice/transcribe")
def voice_transcribe(filename: str):
    """Transcribes an audio file already present under Data/Audio/ or Data/Voice/."""
    path = _resolve_audio_path(filename)
    voice = Voice()
    return voice.transcribe(str(path))


@app.post("/api/voice/listen")
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


@app.post("/api/voice/watch")
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


@app.post("/api/voice/unwatch")
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


@app.post("/api/voice/answer")
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


@app.post("/api/voice/hold")
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


@app.get("/api/voice/control")
def voice_control():
    """Whether a key is held, whether an answer is waiting for a take, and
    whether the question being said is interrupted -- by either of those, or
    by speech over it that a watch heard."""
    return control.snapshot()


@app.get("/api/voice/history")
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


@app.get("/api/voice/transcript")
def voice_transcript():
    """The take being transcribed, or the last one: its segments, the words
    struck, and the text so far."""
    if transcript is None:
        return {"take": None, "segments": [], "text": ""}
    return transcript.snapshot()


@app.post("/api/voice/strike")
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
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")


@app.get("/api/voice/conversation/state")
def voice_conversation_state():
    """The current state, the recent events, and the microphone level, once."""
    return conversation.snapshot()


@app.post("/api/voice/conversation")
async def voice_conversation_post(request: Request):
    """A dialog's own state, posted by the program asking the question.

    Body: `{"state": ..., "text": ..., "reason": ...}`. Only the dialog's
    states are accepted (`speaking`, `recorded`, `gave_up`, `idle`); the
    microphone's are joe's to report.
    """
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")
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


@app.get("/api/voice/conversation")
async def voice_conversation(request: Request):
    """The conversation's states as they happen, as server-sent events."""
    return StreamingResponse(
        _conversation_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/voice/level")
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
