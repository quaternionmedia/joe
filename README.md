# Joe

Joe (named after Joseph Fourier) is an audio workbench for turning audio files into chroma visualizations and MIDI outputs.

The repo has two primary parts:

- Python backend/analysis pipeline (`Modules/`, `main.py`, `api.py`)
- p5.js + Vite frontend (`src/`)

## Quickstart

### Prerequisites

- Python `3.11.x` (required by `pyproject.toml`)
- Node.js + npm
- [`uv`](https://docs.astral.sh/uv/) (recommended) **or** `pdm` / `venv+pip`

### Recommended: uv

Install everything and launch both servers in one step:

```powershell
uv sync
npm install
uv run joe dev       # Vite :3000 + API :8000
```

Then in a second terminal, run the pipeline:

```powershell
uv run joe run       # processes Data/Audio/ → Data/Output/
```

Open `http://localhost:3000/joe`, click **Results → Fetch Latest**.

### CLI commands

| Command | What it does |
| --- | --- |
| `uv run joe frontend` | Vite dev server only (`localhost:3000`) |
| `uv run joe backend` | FastAPI API server only (`localhost:8000`) |
| `uv run joe dev` | Both servers (Ctrl+C to stop) |
| `uv run joe run` | Run the pipeline once |

### Python setup (fallback: pdm)

```powershell
pdm install
pdm run python main.py
```

### Python setup (fallback: venv + pip)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Frontend setup (standalone)

```powershell
npm install
npm run dev
```

### E2E tests (one-time browser install)

```powershell
npx playwright install --with-deps chromium
npm run test:e2e
```

## Verify Setup

Run Python tests:

```powershell
python -m pytest -q
```

Run frontend E2E tests:

```powershell
npm run test:e2e
```

Run backend pipeline:

```powershell
python main.py
```

Expected artifacts are created under `Data/Output/<timestamp>/`:

- `Data/Output/<timestamp>/Chroma/*.png`
- `Data/Output/<timestamp>/MIDI/*.mid`
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`

Input audio is read from `Data/Audio/`.

## Project Structure

- `Data/`: input audio and generated outputs (git-ignored)
- `Modules/`: core Python classes (`Audio`, `Chroma`, `MIDI`, `Note`, utilities)
- `src/`: frontend source (`p5.js` + Vite) — components, config, sketch
- `tests/`: Python unit tests; `tests/e2e/` for Playwright E2E tests
- `docs/`: contributor guide, module reference, API reference
- `api.py`: FastAPI server wrapping the pipeline
- `cli.py`: Typer CLI (`joe frontend | backend | dev | run`)
- `main.py`: backend pipeline entrypoint

## Frontend Architecture

The Vite frontend (`src/`) has three layers:

- **Canvas** — `src/sketch.js` runs a live mic FFT visualiser via `p5.AudioIn` + `p5.FFT`. p5 and p5.sound are loaded as CDN globals (not bundled via Vite) because p5.sound must patch `window.p5` at script-evaluation time. The "Joe, go!" button click resumes the Web Audio context and starts mic capture. Dot size scales on a dB curve (`20·log₁₀(v/255)`) to match human loudness perception.
- **Era panel** — `src/components/EraPanel.js` shows setlist metadata with arrow-key navigation and anime.js cross-fades.
- **Results panel** — `src/components/ResultsPanel.js` loads pipeline output via **"Fetch Latest"** (calls the API) or via the **"Load JSON"** file picker. Renders a piano roll canvas (pitch × time) coloured by transform type: Raw (white), Harmonic (cyan), Percussive (orange).

> **Note:** `npm run build` warns that `outDir` is outside the project root — expected (Vite root is `src/`).

## Contributing

See [docs/contributing.md](docs/contributing.md) for branch naming, required checks, and PR expectations.
