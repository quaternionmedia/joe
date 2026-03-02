# Joe

Joe (named after Joseph Fourier) is an audio workbench for turning audio files into chroma visualizations and MIDI outputs.

The repo has three primary parts:
- Python backend/analysis pipeline
- p5.js + Vite frontend
- Notebooks for exploratory analysis

## Quickstart

### Prerequisites
- Python `3.11.x` (required by `pyproject.toml`)
- Node.js + npm
- Optional: `pdm` (`pip install pdm`)

### Python setup (preferred: pdm)
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

### Frontend setup
```powershell
npm install
npm run dev
npm run build
```

## Verify Setup

Run tests:
```powershell
python -m pytest -q
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

- `Data/`: input audio and generated outputs
- `Modules/`: core Python classes (`Audio`, `Chroma`, `MIDI`, `Note`, utilities)
- `src/`: frontend source (`p5` + Vite)
- `tests/`: Python tests
- `notebooks/`: exploratory notebooks
- `main.py`: backend entrypoint

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, required checks, and PR expectations.
