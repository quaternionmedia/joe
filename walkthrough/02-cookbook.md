# 02 — Cookbook

> **Runtime: hermetic.** No port, no network, no browser. Reads the CLI's,
> the API's and the code's own registries and starts nothing.

For somebody already set up. `01-onboarding.md` is the other document, and they
stay separate on purpose: one page trying to be both serves neither.
`docs/cookbook.md` holds the longer step-by-step recipes.

## Commands

| Command | Does |
| --- | --- |
| `uv run pytest tests walkthrough --doctest-glob=*.md` | The suite and every walkthrough page. Run it before a pull request: it also redraws `walkthrough/media/`, and a picture that changed is committed with the change that changed it |
| `npm run test:e2e` | The Playwright specs under `tests/e2e/`, with joe's API mocked in the browser |
| `npm run build` | The frontend, built into `dist/` |
| `uv run joe dev` | Vite on `localhost:3000` and the API on `localhost:8000`; Ctrl+C stops both |
| `uv run joe frontend` | Vite alone |
| `uv run joe backend` | The API alone |
| `uv run joe run` | The pipeline once, on the first file in `Data/Audio/` |
| `uv run joe serve --host H --port P --api-port A --state DIR` | `joe dev` on the addresses given: the API on `A`, then Vite on `P` with `--strictPort`. Data stays in this checkout's `Data/` |
| `uv run joe check --url U --shots DIR` | `03-in-the-browser` against the joe already serving `U`, with its pictures written to `DIR` |
| `uv run joe voice setup` | Find the microphone while you talk, save it, and prove it with a transcribed sentence |
| `uv run joe voice listen` | Record until you stop talking, then transcribe |
| `uv run joe voice transcribe <path>` | Transcribe an audio file |
| `uv run joe voice devices` | The audio inputs, with the host API that tells same-named ones apart |
| `uv run joe voice level` | How loud an input is right now |

`serve` and `check` are the performing family's demo contract, which the qm
corpus declares once for every member.

That table and the CLI are checked against each other, so a command the CLI
grows and this page does not name is a failing build:

```python
>>> from pathlib import Path
>>> from typer.main import get_command
>>> import cli
>>> group = get_command(cli.app)
>>> sorted(group.commands)
['backend', 'check', 'dev', 'frontend', 'run', 'serve', 'voice']
>>> sorted(group.commands['voice'].commands)
['devices', 'level', 'listen', 'setup', 'transcribe']
>>> page = Path('walkthrough/02-cookbook.md').read_text(encoding='utf-8')
>>> [c for c in group.commands if c != 'voice' and f'`uv run joe {c}' not in page]
[]
>>> [c for c in group.commands['voice'].commands if f'`uv run joe voice {c}' not in page]
[]

```

## Routes

`docs/api.md` is the API's reference, with a `curl` for each route. Each
route has a heading there of the form ``### `GET /api/health` ``, and the
headings and the routes the app serves are the same set, by method and path:

```python
>>> import api, re
>>> served = {(method, route.path) for route in api.app.routes
...           if route.path.startswith(('/api/', '/family/')) for method in route.methods}
>>> reference = Path('docs/api.md').read_text(encoding='utf-8')
>>> headed = set(re.findall(r'^#{2,4} `([A-Z]+) (/(?:api|family)/[^`]+)`', reference, flags=re.M))
>>> sorted(served - headed), sorted(headed - served)
([], [])

```

A substring search would not do: `/api/health` is inside `/api/healthz`.

### The performing family

A hub firing a show's cues reaches joe on two routes of the API's own port --
`--api-port` under `joe serve` -- outside `/api`, so the dev server does not
proxy them:

```python
>>> sorted((method, path) for method, path in served if path.startswith('/family/'))
[('GET', '/family/state'), ('POST', '/family/cue')]

```

| Route | Does |
| --- | --- |
| `POST /family/cue` | `{"cue": {...}, "action": {"take": {"notes": ["C4", "E4"], "seconds_per_note": 0.5}}}`: synthesizes the notes into `Data/Audio/` and runs the pipeline on them. `202` with the state at once; `422 {"ok": false, "error": ...}` for anything else, changing nothing |
| `GET /family/state` | `{"member": "joe", "cue": <the last cue accepted>, "state": {"latest": {"file", "events"} or null, "busy", "error"}}` |

`tests/test_family.py` holds both to those answers, and runs one take through
the real API and the real pipeline. `docs/api.md` has the details.

## Environment

| Variable | Read by | Does |
| --- | --- | --- |
| `JOE_API_URL` | `vite.config.js` | Where the dev server sends `/api`; `http://localhost:8000` unless set |
| `QMCP_URL` | `vite.config.js` | Where the dev server sends `/v1`, qmcp's API; `http://localhost:3141` unless set |
| `JOE_AUDIO_FILE` | `main.py` | One file for the pipeline to process; `POST /api/run/{filename}` sets it |
| `JOE_INPUT_DEVICE` | `Modules/Voice.py` | The microphone, overriding the one `joe voice setup` saved |
| `JOE_LANGUAGE` | `Modules/Voice.py` | The language a take is decoded as; `en` unless set, `auto` to detect |
| `JOE_CUES` | `Modules/Cue.py` | `0` silences the turn tones |
| `JOE_OUTPUT_DEVICE` | `Modules/Cue.py` | The output the tones play on, by a fragment of its name |
| `VOX_OUTPUT_DEVICE` | `Modules/Cue.py` | The same, when `JOE_OUTPUT_DEVICE` is unset: the output qmcp's voice is heard on |
| `JOE_DATAPOINTS` | `Modules/Transcript.py` | `0` writes no segment datapoints |
| `JOE_BARGE_IN` | `Modules/Watch.py` | `0` leaves only the keys to interrupt a question |
| `JOE_BARGE_FACTOR` | `Modules/Watch.py` | How much louder than the question's echo speech must be to interrupt it |
| `JOE_WALKTHROUGH_PORTS` | `walkthrough/support.py` | A `lo-hi` range the browser page, and the family's end-to-end test, take their ports from; the system picks unless set |
| `JOE_WALKTHROUGH_URL` | `walkthrough/support.py` | A joe already up for the browser page to attach to instead of starting one; `joe check` sets it |
| `JOE_WALKTHROUGH_SHOTS` | `walkthrough/support.py` | Where the browser page writes its pictures instead of `walkthrough/media/`; `joe check` sets it |

Every variable the code reads is in that table, and every one in the table is
read somewhere:

```python
>>> import subprocess
>>> tracked = subprocess.run(['git', 'ls-files', '*.py', '*.js'], capture_output=True,
...                          text=True, check=True).stdout.split()
>>> sources = [name for name in tracked if not name.startswith('tests/')]
>>> read = set()
>>> for name in sources:
...     read |= set(re.findall(r'\b(?:JOE|VOX|QMCP)_[A-Z_]+\b', Path(name).read_text(encoding='utf-8')))
>>> tabled = set(re.findall(r'^\| `((?:JOE|VOX|QMCP)_[A-Z_]+)`', page, flags=re.M))
>>> sorted(read - tabled), sorted(tabled - read)
([], [])

```

## What cannot run here

A microphone, a voice and a pair of ears. `docs/manual-test-plan.md` is the
written plan for those, and says which automated check stands nearest each.
