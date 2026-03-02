# Contributing

## Local Setup

### Python
Preferred path:
```powershell
pdm install
```

Fallback path:
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Use Python `3.11.x` for compatibility with `pyproject.toml`.

### Frontend
```powershell
npm install
```

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

If your change affects runtime behavior, also run:
```powershell
python main.py
```

## Pull Request Expectations

Each PR should include:
- Clear summary of what changed and why
- Testing notes (commands executed and result)
- Screenshots or short clips for frontend/UI changes
- Any known limitations or follow-ups

## Docs Policy

If you change commands, paths, setup flow, or contributor workflows, update:
- `README.md`
- `Modules/README.md` (if module behavior/path details changed)
- `CONTRIBUTING.md` (if process/checks changed)
