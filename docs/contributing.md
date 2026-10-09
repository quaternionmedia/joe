# Contributing

## Local Setup

[`walkthrough/01-onboarding.md`](../walkthrough/01-onboarding.md) is the
setup, and it runs: what to install, in what order, and the failure modes,
each checked on the machine that reads it. This guide does not repeat it, so
the two cannot disagree.

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
uv run pytest tests walkthrough --doctest-glob=*.md
npm run build
npm run test:e2e
```

The first runs the Python suite and every walkthrough page, the browser page
among them, and redraws the pictures in `walkthrough/media/`. They are
recorded, never compared: if one changed, look at it, and commit the redrawn
pictures with the change that redrew them.

What no automated check reaches -- a real microphone, a real voice, the tones
-- is in [`docs/manual-test-plan.md`](manual-test-plan.md).

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

## CI Checks

| Workflow | Job | Runs |
| --- | --- | --- |
| `tests.yml` | `pytest`, on Windows and Linux | The Python suite and the hermetic walkthrough pages |
| `e2e.yml` | `playwright`, on Windows | The Playwright specs, then the browser walkthrough page, keeping its pictures as a build artifact |
| `deploy.yml` | `build-and-deploy` | `npm run build`, and the Pages deploy |
