# Joe API Reference

The Joe FastAPI server (`api.py`) provides endpoints for pipeline results, audio capture,
the audio library, and speech analysis.

**Base URL (local dev):** `http://localhost:8000`

The Vite dev server proxies `/api/*` to this address, so the browser can call all endpoints
directly when both servers are running via `joe dev`.

---

## Endpoints

### `GET /api/health`

Returns `200 OK` when the server is up.

**Response**

```json
{ "status": "ok" }
```

**curl**

```bash
curl http://localhost:8000/api/health
```

---

### `GET /api/results/latest`

Returns the content of the most recently written `Process_Data_*.json` file from
`Data/Output/`, sorted by file modification time.

**Response** — `200 OK`

The full `Process_Data` JSON object (same schema as the file on disk). See
[modules.md](modules.md) for the field reference.

**Errors**

| Status | Reason |
| --- | --- |
| `404` | No `Data/Output/` directory, or no JSON files found yet |

**curl**

```bash
curl http://localhost:8000/api/results/latest
```

**Troubleshooting**

- Got `404`? Make sure you've run `joe run` (or `python main.py`) at least once and that
  `Data/Audio/` contains at least one audio file.
- Got `connection refused`? The API server isn't running — start it with `joe backend` or
  `joe dev`.

---

### `POST /api/run`

Runs `python main.py` on all files in `Data/Audio/` and returns its output. Blocks until
the pipeline completes (can take tens of seconds for large audio files).

**Response** — `200 OK`

```json
{
  "returncode": 0,
  "stdout": "...",
  "stderr": ""
}
```

A non-zero `returncode` means the pipeline failed. Check `stderr` for the Python traceback.

**curl**

```bash
curl -X POST http://localhost:8000/api/run
```

---

### `POST /api/run/{filename}`

Run the pipeline on a specific file in `Data/Audio/`. Sets the `JOE_AUDIO_FILE` env var so
`main.py` processes only that file.

**Path parameter**

| Parameter | Description |
| --- | --- |
| `filename` | Name of an audio file in `Data/Audio/` (e.g. `capture_20240101_120000.wav`) |

**Response** — `200 OK` — same shape as `POST /api/run`

| Status | Reason |
| --- | --- |
| `404` | File not found in `Data/Audio/`, or `filename` is not a bare name (contains a path separator, `..` or a NUL byte, or ends in a dot or space) |
| `200` + `returncode: 1` | Unsupported format — check `stderr` for details |
| `200` + `returncode: -1` | Subprocess failed to start or communicate — check `stderr` |
| `200` + `returncode != 0` | Pipeline crashed — check `stderr` for Python traceback |

Supported pipeline formats: `.wav`, `.webm`, `.mp3`, `.ogg`, `.flac`. WebM decoding requires **ffmpeg** to be installed and on `PATH` (librosa uses it via audioread). WAV, MP3, OGG, and FLAC work without ffmpeg.

**curl**

```bash
curl -X POST http://localhost:8000/api/run/capture_20240101_120000.wav
```

---

### `POST /api/capture/start`

Start recording from the default system audio input via sounddevice. The WAV file is written
live to `Data/Audio/`.

**Response** — `200 OK`

```json
{ "status": "recording", "filename": "capture_20240101_120000.wav" }
```

**Errors**

| Status | Reason |
| --- | --- |
| `400` | Already recording |

**curl**

```bash
curl -X POST http://localhost:8000/api/capture/start
```

---

### `POST /api/capture/stop`

Stop the active backend recording and flush the WAV file to disk.

**Response** — `200 OK`

```json
{ "status": "stopped", "filename": "capture_20240101_120000.wav" }
```

**Errors**

| Status | Reason |
| --- | --- |
| `400` | Not currently recording |

**curl**

```bash
curl -X POST http://localhost:8000/api/capture/stop
```

---

### `POST /api/audio/upload`

Accept a raw audio blob from the browser (recorded via `MediaRecorder`) and save it to
`Data/Audio/`. Content-Type determines the file extension (`.wav` or `.webm`).

**Request body** — raw audio bytes

**Headers**

```http
Content-Type: audio/wav   ->  saves as capture_<timestamp>.wav
Content-Type: audio/webm  ->  saves as capture_<timestamp>.webm
```

**Response** — `200 OK`

```json
{ "filename": "capture_20240101_120000.webm" }
```

**curl**

```bash
curl -X POST http://localhost:8000/api/audio/upload \
  -H "Content-Type: audio/webm" \
  --data-binary @recording.webm
```

---

### `GET /api/audio/files`

List all audio files in `Data/Audio/`, sorted by modification time (newest first).

**Response** — `200 OK`

```json
[
  { "name": "capture_20240101_120000.wav", "size": 2097152, "mtime": 1704067200.0 },
  { "name": "capture_20231231_235900.webm", "size": 512000, "mtime": 1704067140.0 }
]
```

Supported extensions: `.wav`, `.webm`, `.mp3`, `.ogg`, `.flac`

**curl**

```bash
curl http://localhost:8000/api/audio/files
```

---

### `GET /api/audio/{filename}`

Serve an audio file from `Data/Audio/` for browser playback. Returns the file with the
appropriate `Content-Type` for the browser's `<audio>` element.

**Path parameter**

| Parameter | Description |
| --- | --- |
| `filename` | Name of a file in `Data/Audio/` |

**Errors**

| Status | Reason |
| --- | --- |
| `404` | File not found in `Data/Audio/`, or `filename` is not a bare name (contains a path separator, `..` or a NUL byte, or ends in a dot or space) |

**curl**

```bash
curl -o recording.wav http://localhost:8000/api/audio/capture_20240101_120000.wav
```

---

### `GET /api/voice/devices`

Lists the audio input devices *the server's machine* can see, and which one
is default. Query this before relying on `/api/voice/listen` — recording
happens wherever `joe backend` is running, not wherever the caller is, so
"is there a microphone" is a question about that machine.

**Response** — `200 OK`

```json
{
  "devices": [
    { "index": 1, "name": "USB Microphone", "channels": 2, "default": true,
      "hostapi": "Windows WASAPI" }
  ],
  "microphone_available": true
}
```

An empty `devices` list (and `microphone_available: false`) means the server
has no usable input device, or its audio backend itself couldn't be reached
— both report the same way rather than one of them crashing.

**curl**

```bash
curl http://localhost:8000/api/voice/devices
```

---

### `POST /api/voice/transcribe`

Transcribes an audio file already present under `Data/Audio/` or `Data/Voice/` using
whisper. `filename` is a name relative to one of those two directories — paths that
resolve outside them are rejected.

**Query params**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `filename` | str | — | required; filename under `Data/Audio/` or `Data/Voice/` |

**Response** — `200 OK`

```json
{ "text": "...", "segments": [...], "language": "en" }
```

**Errors**

| Status | Reason |
| --- | --- |
| `404` | No such file under `Data/Audio/` or `Data/Voice/` |

**curl**

```bash
curl -X POST "http://localhost:8000/api/voice/transcribe?filename=clip.wav"
```

---

### `POST /api/voice/listen`

Records `duration` seconds (default `5.0`, max `60`) from an input device,
writes it to `Data/Voice/`, and transcribes the result.

The device is opened at *its* native sample rate and channel count, and the
audio is downmixed and resampled to 16 kHz mono afterwards. Asking a device
to open at 16 kHz fails on most of them — one machine here has twenty inputs
and every one refused, WASAPI saying "Invalid sample rate" and the others
less.

**Query params**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `duration` | float | `5.0` | the most seconds to record, `0 < duration <= 60` |
| `until_silence` | bool | `true` | stop when the speaker stops: sustained speech starts the take and `silence_ms` of quiet after it ends it. `false` records the whole `duration` |
| `silence_ms` | int | `800` | trailing quiet that ends an endpointed take, `100..5000` |
| `device` | string | *see below* | an input index, or a fragment of a device name. A fragment matching several devices is a `503` rather than a guess. Omitted: `JOE_INPUT_DEVICE` if set, else the microphone `joe voice setup` saved, else the backend default. |
| `hint` | string | none | the words a short answer is expected to be, comma-separated (`approve, hold`), handed to the transcriber as its prompt. It biases and never constrains: what was heard is what comes back. At most 500 characters |

A take is transcribed as English (`JOE_LANGUAGE` names another; `auto`
detects), as one utterance, and, when it is short, with a beam search: a
one-word answer gives whisper's language detection nothing to go on and a
greedy first guess nothing to recover from. The expected words matter most
where the first syllable was clipped. A prompt that is echoed back on unclear
audio names every option, which a dialog reads as no match and asks again.

**Response** — `200 OK`

```json
{ "text": "...", "segments": [...], "language": "en", "audio_path": "Data/Voice/capture_...wav", "speech_detected": true }
```

`confidence` says how sure the transcriber was, from 0 to 1: the lowest of its
segments' mean token probabilities (whisper's `exp(avg_logprob)`), struck
segments left out, `1.0` for an answer given by key, and `null` when nothing
was weighed. A dialog can skip asking for confirmation above a threshold of its
own.

`speech_detected` is `true` or `false` for an endpointed take and `null` for a
fixed one. When the endpointer heard no speech, the transcriber is not run and
`text` is empty -- no speech is a known answer, which a caller can report as
"heard nothing" rather than as a failed transcription.

**Errors**

| Status | Reason |
| --- | --- |
| `400` | `duration` outside `0 < duration <= 60`, or a `hint` over 500 characters |
| `503` | No microphone available, no device matching `device`, several devices matching it, or a device that opened and returned samples outside `[-1, 1]` |

**curl**

```bash
curl -X POST "http://localhost:8000/api/voice/listen?duration=5"
curl -X POST "http://localhost:8000/api/voice/listen?duration=5&device=USB"
```

---

### `POST /api/voice/level`

How loud one input device is right now. Records briefly and keeps nothing.

This is the route for choosing between devices whose names do not
distinguish them — the same microphone appears once per host API under the
same name, and no listing says which one a voice actually arrives on. Speak,
and read the peaks.

**Query params**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `duration` | float | `1.0` | seconds to record, `0 < duration <= 10` |
| `device` | string | *the backend default* | as for `/api/voice/listen` |

**Response** — `200 OK`

```json
{ "device": 12, "name": "USB Microphone", "peak": 0.0812, "rms": 0.0091, "silent": false }
```

`silent` is the useful field: a device returning digital silence is either
the wrong one or muted, and a device list cannot tell those apart.

**Errors**

| Status | Reason |
| --- | --- |
| `400` | `duration` outside `0 < duration <= 10` |
| `503` | No such device, an ambiguous name, or a device that opened and returned samples outside `[-1, 1]` |

**curl**

```bash
curl -X POST "http://localhost:8000/api/voice/level?device=12"
```

---

### `GET /api/voice/conversation`

The conversation's states as they happen, as server-sent events. The front
end's voice panel reads this stream.

The states follow the polite conversation protocol, in the order a turn moves
through them:

| State | Meaning | Reported by |
| --- | --- | --- |
| `speaking` | the question is being asked; the microphone is closed | the dialog |
| `listening` | the microphone is open; nobody has started talking | joe |
| `holding` | a key is held: the turn stays open through pauses until it is released | joe |
| `transcript` | the take as it is written: `take`, `segments` (`index`, `start`, `end`, `words`, `struck`, `pending`) and `text`; not a turn of its own | joe |
| `hearing` | speech is sustained; the listener does not interrupt | joe |
| `pausing` | the speech stopped; the turn is held open a moment longer | joe |
| `transcribing` | the turn has ended; the words are being read | joe |
| `heard` | what was said, in `text` | joe |
| `no_speech` | the turn ran to its cap and nobody spoke | joe |
| `recorded` | an answer was accepted, in `text` | the dialog |
| `gave_up` | no usable answer; nothing recorded | the dialog |
| `idle` | nothing is happening | the dialog, or joe when the microphone fails |

Each event is `{"seq", "state", "text", "at"}`, plus `reason` (`noinput` or
`nomatch`) on a `speaking` event that re-asks. A connection first receives the
recent events, then each new one; a reconnect sending `Last-Event-ID` resumes
after it. The microphone's level arrives as its own event type, `level`, with
`{"rms", "threshold", "seq"}`; `threshold` is null while the room is measured.

```bash
curl -N http://localhost:8000/api/voice/conversation
```

### `GET /api/voice/conversation/state`

The current state, the recent events and the level, once:
`{"state", "events": [...], "level": {...}}`.

### `POST /api/voice/conversation`

A dialog's own state, posted by the program asking the question.

**Body** — `{"state": "speaking", "text": "Voice check. Say approve or hold.", "reason": null, "options": ["approve", "hold"]}`

Only `speaking`, `recorded`, `gave_up` and `idle` are accepted. The other
states are the microphone's, and joe reports them itself while
`/api/voice/listen` records. A `speaking` state may carry the question's
`options`, at most nine, in the order it says them; the page offers each as a
button and a number key.

**Errors**

| Status | Reason |
| --- | --- |
| `400` | A body that is not JSON, a state the dialog may not post, or `options` on another state, over nine, or not all non-empty strings |

### `POST /api/voice/answer`

An answer given without speaking -- a button or a key on the page -- taken as
if it had been said. The take in progress ends at once and `/api/voice/listen`
returns the answer as its `text`, with `"source": "key"` and an empty
`audio_path`; with no take in progress, the next one returns it without opening
the microphone, if it starts within fifteen seconds.

**Body** — `{"text": "approve"}`, at most 100 characters.

**Response** — `200 OK`, `{"held": false, "answer_waiting": true}`

### `POST /api/voice/hold`

A held key. **Body** — `{"held": true}` when pressed, `{"held": false}` when
released. While held, a take neither ends on a pause nor at its `duration`
(it may run to sixty seconds), and the release ends it as speech: the person
said they were speaking. The take reports `holding` when it sees the hold.

**Response** — `200 OK`, `{"held": true, "answer_waiting": false}`

### `GET /api/voice/control`

`{"held", "answer_waiting"}`, once.

### The live transcript

An endpointed take is cut into segments at the half-second pauses inside it,
held or not, and each segment is transcribed as soon as it ends, with the
take's hint and earlier words as the prompt; a `transcript` event carries each
step. `/api/voice/listen` returns the take's text as the segments' words minus
any struck, and a `take` naming it. A segment saying "scratch that", "strike
that" or "delete that" strikes itself and the segment before.

### `POST /api/voice/strike`

Strike a word of the take being transcribed, or restore a struck one.
**Body** -- `{"take": "...", "segment": 0, "word": 2}`, or `{"take": "...",
"last": true}` for the last word still standing. **Response** -- the take's
transcript. `400` for a malformed body, `404` for no such word, `409` for a take
that is no longer the current one.

### `GET /api/voice/transcript`

The take being transcribed, or the last one: `{"take", "segments", "text"}`.

### Datapoints

Every segment is written as `Data/Voice/segments/<take>/<index>.wav` and as a
line of `Data/Voice/segments.jsonl`, one JSON object per line with a `kind`:

| `kind` | Carries |
| --- | --- |
| `segment` | `take`, `index`, `audio`, `start_s`, `end_s`, `duration_s`, `peak_rms`, `mean_rms`, `threshold`, `noise_floor`, `hint`, `prompt`, `model`, `language`, `beam_size`, `avg_logprob`, `no_speech_prob`, `compression_ratio`, `text`, `transcribe_s` |
| `edit` | `take`, `index`, `word`, `text`, `action` (`strike` or `restore`) |
| `take` | `take`, `audio`, `source` (`voice` or `key`), `hint`, `text`, `segments`, `struck` |
| `outcome` | `take`, `state` (`recorded` or `gave_up`), `text` -- what the dialog asking made of the last take, from its post to the conversation route |

Each also carries `at`, seconds since the epoch. `JOE_DATAPOINTS=0` writes none,
and nothing deletes them.

### Cues

Before a listen that answers a question -- the last conversation state is
`speaking` -- joe plays two rising notes and only then opens the microphone,
so the tone is never recorded. Once a take has ended and is being read, or an
answer by key was taken, it plays one lower note. A listen that follows a
silent one plays nothing. `JOE_CUES=0` turns both off; a cue that cannot play
is skipped. They play on the default output unless `JOE_OUTPUT_DEVICE`, or
`VOX_OUTPUT_DEVICE`, names another by a fragment of its name; of an output
listed under several host APIs, MME's is played to, and a fragment naming two
different outputs is refused.

---

## Interactive docs

FastAPI auto-generates an interactive API explorer at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc:      <http://localhost:8000/redoc>

## Typical workflows

```bash
# 1. Start both servers
uv run joe dev

# 2a. Record from the browser
#     Open http://localhost:3000/joe
#     Click "Joe, go!" -> select "Browser" -> click "Live" -> speak -> click "Stop"
#     Recording auto-loads into the transport bar; open "Library" -> click "Process"

# 2b. Record from the backend
curl -X POST http://localhost:8000/api/capture/start
# ... wait ...
curl -X POST http://localhost:8000/api/capture/stop

# 3. Process a specific recording
curl -X POST http://localhost:8000/api/run/capture_20240101_120000.wav

# 4. View results — "Results" -> "Fetch Latest"
#    (auto-opens after clicking "Process" in the Library panel)

# 5. Drop audio into Data/Audio/ and run the full pipeline
curl -X POST http://localhost:8000/api/run
```
