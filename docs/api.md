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
| `duration` | float | `5.0` | seconds to record, `0 < duration <= 60` |
| `device` | string | *the backend default* | an input index, or a fragment of a device name. A fragment matching several devices is a `503` rather than a guess. Falls back to `JOE_INPUT_DEVICE`. |

**Response** — `200 OK`

```json
{ "text": "...", "segments": [...], "language": "en", "audio_path": "Data/Voice/capture_...wav" }
```

**Errors**

| Status | Reason |
| --- | --- |
| `400` | `duration` outside `0 < duration <= 60` |
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
