# Contributing

## Local Setup

### Recommended: uv

[`uv`](https://docs.astral.sh/uv/) manages the Python environment and exposes the `joe` CLI:

```powershell
uv sync          # install Python deps (including fastapi, uvicorn, typer)
npm install      # install Node deps
```

`uv.lock` is the one source of truth for Python dependencies; there is no
pip or pdm fallback. Use Python `3.11.x` for compatibility with
`pyproject.toml`.

### Playwright (one-time)

```powershell
npx playwright install --with-deps chromium
```

## Dev Server Workflow

The `joe` CLI launches frontend and backend independently for easier troubleshooting:

```powershell
# Start everything, every capability on, on loopback (docs/security.md)
uv run joe dev

# Or start separately (useful for isolating issues):
uv run joe frontend                  # Vite only → http://localhost:3000/joe
uv run joe backend --allow library   # API only  → http://localhost:8000/api/health

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

Each user path, step by step -- the music page, the voice loop, joe as a
server -- is a page in [paths/](paths/README.md).

---

## UI Control Groups

The bottom transport bar has five groups, left to right:

| Group | Controls | Purpose |
| --- | --- | --- |
| **1. Audio context** | `Joe, go!` | Resumes the Web Audio context (required once per page load). Turns green when active. |
| **2. Live capture** | `Browser mic\|joe's mic` select + `Live` button + red dot | Sets where Live records from; `Live` starts/stops recording. Disabled until **Joe, go!** is clicked. |
| **3. Transport** | `LIVE\|RESULTS` badge + `Play` + `Stop` + scrub + time + filename + `×` | Plays back a loaded audio file; badge shows canvas mode. Play/Stop disabled while recording. `×` ejects the current source. |
| **4. Windows** | `♫` Library + `▤` Results + `¶` Transcript + `▦` Panels | Each opens its window beside the visualiser, or closes it when it is in front; `▦`, the Panels menu, lists every window and resets the layout. [ui.md](ui.md) describes the dock. |
| **5. Voice** | `Instruct by voice` | One spoken instruction into qmcp's inbox; the outcome shows in the voice panel. |

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
| **Library** is greyed and says "The library is off." | joe was started with `uv run joe backend`, or `dev --allow` without `library` | `uv run joe dev`, or `--allow library` (`JOE_ALLOW_LIBRARY=1`); [security.md](security.md) says what each capability exposes |
| `Live` starts but no notes appear | Mic permission denied or wrong source | Check browser mic permissions; try **joe's mic** |
| `Play` button is greyed out | Live recording is active | Click **Stop** to end recording first |
| **Fetch Latest** returns 404 | No pipeline output yet | Run `uv run joe run` (or process a file via Library) |
| joe's mic capture fails silently | `sounddevice` not installed or no device | Check `uv sync` completed; verify audio input device |

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

Run before opening a PR. `tests.yml` runs the same suite, less the test marked
`local`, which opens this machine's audio and which the runners, with no audio
server, leave out; `deploy.yml` runs the same build ([CI](#ci)):

```powershell
uv run --frozen pytest tests/ -q
npm run build
```

The media tests skip without ffmpeg. With none on `PATH`, name one in
`JOE_FFMPEG`, so they run here as they do in CI on Linux.

If your change affects frontend behaviour, also run the E2E tests and the
lane check, as CI does:

```powershell
npm run check:paths
npm run test:e2e
```

A change to what a person or a program does starts on its lane's page in
[paths/](paths/README.md): the step, and the spec or test that will check it,
written before the change and red until it is made. `npm run check:paths`
fails while a spec is not a step of its lane's page.

If it affects runtime behaviour, also run the backend pipeline, which no CI
job runs:

```powershell
uv run python main.py
```

## Frontend Testing

E2E tests live in `tests/e2e/` and use [Playwright](https://playwright.dev/).
`playwright.config.js` starts the Vite dev server itself, or outside CI
reuses one already on port 3000.

```powershell
npm run test:e2e
```

`playwright.config.js` starts the specs' own servers and never reuses one: the
page on port 3100, and on 3199 a stand-in for joe's API and qmcp's queue
(`tests/e2e/no-backend.mjs`) that answers every request a spec has not
scripted with a 503. A joe, a qmcp or a dev page running on this machine never
answers a spec, and the specs run beside them.

Outside CI an HTML report is written to `playwright-report/` (git-ignored). To open it after a run:

```powershell
npx playwright show-report
```

Every spec is a step of a lane's page in [paths/](paths/README.md) and carries
that lane's tag, so one lane runs on its own:

```powershell
npx playwright test --grep @music-page
npx playwright test --grep @voice-loop
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
- `docs/modules.md` (if module behaviour/path details changed)
- `docs/contributing.md` (if process/checks changed)
- `docs/paths/` (if what a person or a program does changed: the step, and what checks it)
- `docs/ui.md` (if a window, or how the dock keeps them, changed)

## CI

GitHub Actions runs three workflows, none of them filtered by path:

| Workflow | When | Runs on | What it does |
| --- | --- | --- | --- |
| `tests.yml` | Every PR, and every push to `main` | `windows-latest` and `ubuntu-latest`, neither cancelled when the other fails | `uv sync --frozen`, then `uv run --frozen pytest tests/ -q -m "not local"`. Linux installs `ffmpeg` first and no audio library; Windows installs no ffmpeg, so the media tests that need one skip there |
| `e2e.yml` | Every PR, every push to `main`, and by hand | `windows-latest`, Node 22 | `npm ci`, `npx playwright install --with-deps chromium`, `npm run check:paths`, then `npm run test:e2e` |
| `deploy.yml` | Every PR against `main`, every push to `main`, and by hand | `ubuntu-latest` | `npm ci` and `npm run build`; then, only for a push to `main` or a run by hand on `main`, publishes `dist/` to the `gh-pages` branch |

A PR's build is checked, never published. Only `deploy.yml`'s publish can
write, and it runs no project code: `npm ci` and the project's scripts run
in the first job, with a read-only token, and the publish takes its build
([security.md](security.md#the-deploy-workflow); `tests/test_workflows.py`
holds both). No CI job runs `main.py`. No runner has the whisper model
cached, so the `whisper_model` test skips in CI.

Dependabot opens update PRs every Wednesday for the workflows' actions and
for npm packages. npm's minor and patch updates are grouped: one PR for
production dependencies, one for development. It does not watch Python
dependencies: `uv.lock` changes only by hand.
