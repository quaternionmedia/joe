# Contributing

## Local Setup

### Recommended: uv

[`uv`](https://docs.astral.sh/uv/) manages the Python environment and exposes the `joe` CLI:

```powershell
uv sync          # install Python deps (including fastapi, uvicorn, typer)
npm install      # install Node deps
```

### Fallback: pdm

```powershell
pdm install
```

### Fallback: venv + pip

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Use Python `3.11.x` for compatibility with `pyproject.toml`.

### Playwright (one-time)

```powershell
npx playwright install --with-deps chromium
```

## Dev Server Workflow

The `joe` CLI launches frontend and backend independently for easier troubleshooting:

```powershell
# Start everything
uv run joe dev

# Or start separately (useful for isolating issues):
uv run joe frontend   # Vite only → http://localhost:3000/joe
uv run joe backend    # API only  → http://localhost:8000/api/health

# Run the pipeline
uv run joe run
```

**Data flow:**

1. Drop audio into `Data/Audio/`
2. `uv run joe run` → generates `Data/Output/<timestamp>/Process_Data_*.json`
3. In the browser: open **Results** panel → click **Fetch Latest**
4. If "Fetch Latest" shows an error, check the API server is running and visit
   `http://localhost:8000/api/results/latest` directly to inspect the response.

See [api.md](api.md) for endpoint reference and `curl` examples.

For practical end-to-end workflows, see [cookbook.md](cookbook.md).

---

## UI Control Groups

The bottom transport bar has four groups, left to right:

| Group | Controls | Purpose |
| --- | --- | --- |
| **1. Audio context** | `Joe, go!` | Resumes the Web Audio context (required once per page load). Turns green when active. |
| **2. Live capture** | `Browser\|Backend` select + `Live` button + red dot | Sets the capture source; `Live` starts/stops recording. Disabled until **Joe, go!** is clicked. |
| **3. Transport** | `LIVE\|RESULTS` badge + `Play` + `Stop` + scrub + time + filename + `×` | Plays back a loaded audio file; badge shows canvas mode. Play/Stop disabled while recording. `×` ejects the current source. |
| **4. Panels** | `Library` + `Results` | Slide-in panels for audio file management and analysis output. |

**Dependency chain:**

```text
Joe, go!  ->  enables Live  ->  recording  ->  stop  ->  Library: Process  ->  Results loads
  (user gesture              (disables                  (pipeline runs)     (canvas = RESULTS)
   for Web Audio)             transport)
```

**Canvas modes** shown by the badge in the transport bar:

- `LIVE` — real-time scrolling note detections from the mic (while recording)
- `RESULTS` — static piano roll from pipeline JSON (pitch x time, coloured by transform type)
- *(no badge)* — idle, or after eject with no active source; scrubber may scan frozen live layer

### Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Live` button is greyed out | Web Audio not started | Click **Joe, go!** first |
| `Live` starts but no notes appear | Mic permission denied or wrong source | Check browser mic permissions; try **Backend** mode |
| `Play` button is greyed out | Live recording is active | Click **Stop** to end recording first |
| **Fetch Latest** returns 404 | No pipeline output yet | Run `uv run joe run` (or process a file via Library) |
| Red dot pulses but canvas is blank | `Joe, go!` not clicked | Click **Joe, go!** — Web Audio must be started before FFT is active |
| Backend capture fails silently | `sounddevice` not installed or no device | Check `uv sync` completed; verify audio input device |

---

## Branch Naming

Use short descriptive branch names with a scope prefix:

- `docs/<topic>`
- `fix/<topic>`
- `feat/<topic>`
- `chore/<topic>`

Examples:

- `docs/onboarding-hardening`
- `fix/test-import-path`

## Required Pre-PR Checks

Run before opening a PR:

```powershell
python -m pytest -q
npm run build
```

If your change affects frontend behaviour, also run E2E tests:

```powershell
npm run test:e2e
```

If your change affects runtime behaviour, also run the backend pipeline:

```powershell
python main.py
```

## Frontend Testing

E2E tests live in `tests/e2e/` and use [Playwright](https://playwright.dev/).

```powershell
npm run test:e2e
```

Reports are written to `playwright-report/` (git-ignored). To open the HTML report after a run:

```powershell
npx playwright show-report
```

Test coverage:

- Page load — canvas renders, no JS errors
- "Joe, go!" button present and clickable
- Arrow-key setlist navigation does not crash
- Pipeline JSON contract — fixture validates the shape of `Process_Data_*.json`

## Pull Request Expectations

Each PR should include:

- Clear summary of what changed and why
- Testing notes (commands executed and result)
- Screenshots or short clips for frontend/UI changes
- Any known limitations or follow-ups

## Docs Policy

If you change commands, paths, setup flow, or contributor workflows, update:

- `README.md`
- `docs/modules.md` (if module behaviour/path details changed)
- `docs/contributing.md` (if process/checks changed)

## Expected CI Checks

A GitHub Actions workflow on PRs would run:

| Check | Command | When |
| --- | --- | --- |
| Python tests | `python -m pytest -q` | Always |
| Frontend build | `npm run build` | Always |
| E2E tests | `npm run test:e2e` | PRs touching `src/` |
| Backend pipeline | `python main.py` | PRs touching `Modules/` or `main.py` |
