# Joe API Reference

The Joe FastAPI server (`api.py`) provides three endpoints for integrating the Python pipeline
with the frontend, and for ad-hoc troubleshooting.

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

## Interactive docs

FastAPI auto-generates an interactive API explorer at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc:      <http://localhost:8000/redoc>
