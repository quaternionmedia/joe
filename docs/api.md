# Joe API Reference

The Joe FastAPI server (`api.py`) provides endpoints for integrating the Python pipeline
with the frontend, for ad-hoc troubleshooting, and for speech analysis.

**Base URL (local dev):** `http://localhost:8000`

The Vite dev server also proxies `/api/*` to this address, so the browser can call
`/api/results/latest` directly when both servers are running via `joe dev`.

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

Runs `python main.py` as a subprocess and returns its output. Blocks until the pipeline
completes (can take tens of seconds for large audio files).

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

**Typical workflow**

```bash
# Drop audio into Data/Audio/, then:
curl -X POST http://localhost:8000/api/run
# Open Results panel in the browser → click "Fetch Latest"
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
    { "index": 1, "name": "USB Microphone", "channels": 2, "default": true }
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

Records `duration` seconds (default `5.0`, max `60`) from the server's default
microphone, writes it to `Data/Voice/`, and transcribes the result.

**Query params**

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `duration` | float | `5.0` | seconds to record, `0 < duration <= 60` |

**Response** — `200 OK`

```json
{ "text": "...", "segments": [...], "language": "en", "audio_path": "Data/Voice/capture_...wav" }
```

**Errors**

| Status | Reason |
| --- | --- |
| `400` | `duration` outside `0 < duration <= 60` |
| `503` | No microphone available on the server's machine — check `GET /api/voice/devices` |

**curl**

```bash
curl -X POST "http://localhost:8000/api/voice/listen?duration=5"
```

---

## Interactive docs

FastAPI auto-generates an interactive API explorer at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc:      <http://localhost:8000/redoc>
