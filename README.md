# Joe

Joe (named after Joseph Fourier) does two jobs on one workstation:

- **An audio workbench.** It turns audio files into chroma visualizations and
  MIDI, and shows them on a p5.js page beside a live microphone FFT and a
  piano roll.
- **The speech engine of a voice-driven development loop.** It owns the
  microphone, transcribes what is said with whisper, and shows each turn of a
  spoken conversation on its page. [qmcp](https://github.com/quaternionmedia/qmcp),
  the local model backend, runs from its own checkout: it asks the questions,
  records instructions, asks consent, and has the local model it stands up
  read the project and answer, and joe hears the answers.

The repo has three parts:

- the analysis pipeline (`Modules/`, `main.py`)
- the FastAPI backend (`api.py`): the pipeline's routes and the speech
  engine's `/api/voice/*` routes
- the p5.js + Vite frontend (`src/`)

## Quickstart

### Prerequisites

- Python `3.11.x` (required by `pyproject.toml`)
- Node.js + npm
- [`uv`](https://docs.astral.sh/uv/); `uv.lock` is the one lockfile

### Install and run

Install everything and launch both servers in one step:

```powershell
uv sync
npm install
uv run joe dev       # Vite :3000 + API :8000
```

Then in a second terminal, run the pipeline:

```powershell
uv run joe run       # processes Data/Audio/ -> Data/Output/
```

Open `http://localhost:3000/joe`, click **Results → Fetch Latest**.

### CLI commands

| Command | What it does |
| --- | --- |
| `uv run joe frontend` | Vite dev server only (`localhost:3000`) |
| `uv run joe backend` | FastAPI API server only (`localhost:8000`) |
| `uv run joe dev` | Both servers (Ctrl+C to stop) |
| `uv run joe run` | Run the pipeline once |
| `uv run joe voice setup` | **Start here for voice.** Find your microphone while you talk, save it, and prove it with a transcribed sentence |
| `uv run joe voice listen [--device N] [--fixed]` | Record until you stop talking, then transcribe (`--fixed` records the whole `--duration`) |
| `uv run joe voice transcribe <path>` | Transcribe an audio file to text |
| `uv run joe voice devices` | List audio input devices, with the host API that distinguishes same-named ones; `S` marks the saved microphone |
| `uv run joe voice level [--device N] [--every]` | How loud an input is right now |

### The voice loop

Two servers, one per checkout: `uv run joe dev` here and, in qmcp's,
`uv run qmcp serve --converse --runtime local`. Nothing after those two is
typed. qmcp says it is ready and asks what should be done; an instruction is
read back and recorded -- heard confidently, unless interrupted; otherwise on
"agree" -- consent is asked aloud and given with
"approve", the local model reads the project, the answer is said back, and it
asks whether there is anything else. Questions agents have queued are asked in
between, and "stop listening" ends it. This page shows every turn live. Started
without `--converse`, the buttons below start one turn each instead. qmcp's
`docs/voice-loop-demo.md` and `docs/integrations/voice.md` are the pages for
that half.

**Voice, the first time:** run `uv run joe voice setup` and keep talking when
it says so. Once a test sentence has recorded from the microphone that heard
you, it saves that microphone to `Data/voice-device.json`, and every
recording — the CLI's and the backend's —
uses it from then on, with no environment variable to set and no restart.
`JOE_INPUT_DEVICE`, where set, still overrides it.

**Watching a conversation:** with `uv run joe dev` running, the page at
`http://localhost:3000/joe` shows a voice panel whenever something is spoken
through the backend: asking, your turn, hearing you, pause, reading, and the
answer. Each state has its own colour, motion and label. The backend reports
the microphone's states itself; the program asking the question posts the
rest (`docs/api.md`, `/api/voice/conversation`).

**Answering by voice from the page:** with qmcp's server running as well
(`uv run qmcp serve` in its checkout), whatever is waiting on you in
qmcp appears in the panel, oldest first, with **Answer by voice**. Pressing it
has qmcp ask the question aloud while joe's microphone hears the answer, and
the panel shows the turn as it happens. Nothing is spoken until the button is
pressed. If the conversation cannot start, the panel shows qmcp's own reason.
The dev server reaches qmcp at `http://localhost:3141`; `QMCP_URL` moves it.

**Instructing by voice from the page:** **Instruct by voice** in the bottom bar
has qmcp ask aloud what should be done and take the answer into its
instruction inbox; the panel shows the turn, and when it ends, the newest row
in the inbox — the words, the project they resolved to or "no project", and
whether the row is recorded or unresolved. A qmcp without the inbox answers
404, and the panel says so; the queue above keeps working.

**Answering without speaking, and following by ear:** a question's answers
appear in the panel as numbered buttons, and with the page focused the keys do
the same without looking:

| Key | Does |
| --- | --- |
| `1`–`9` | answers with the question's options, in the order it says them |
| `R` | asks for it to be said again |
| `Shift`+`Esc` | stops listening |
| `~`, held | keeps the turn open through pauses; releasing it ends the turn |

A key or button counts as having said the word: the turn in progress ends at
once. **A question can be answered before it ends:** a key, the held `~`, or
speech louder than the question's own echo stops the question mid-sentence,
and a spoken answer is kept from its first word. Through speakers, speak up
over the voice or use the keys; with headphones, any speech does it.
`JOE_BARGE_IN=0` leaves only the keys. Two short tones carry what the panel shows: two rising notes just before
the microphone opens for an answer, and one lower note once the turn has been
heard. They play only after a question, never through a silent wait, and
`JOE_CUES=0` turns them off. They play on the system's default output unless
`JOE_OUTPUT_DEVICE` (or `VOX_OUTPUT_DEVICE`, the output qmcp's voice is heard
on) names another by a fragment of its name.

**The transcript as it is written:** a take is transcribed piece by piece
while it is spoken, and the panel shows the words as they arrive. Clicking a
word strikes it, or restores it; Backspace strikes the last word still
standing; saying "scratch that" strikes what came just before. The take's text
leaves struck words out, so what is read back is what the panel showed.

**Every piece is kept for tuning:** each stretch of speech is written as its
own WAV under `Data/Voice/segments/` and described in `Data/Voice/segments.jsonl`
-- its timing and levels, the hint and prompt it was decoded with, whisper's
own confidence, the text, the words struck, and what the dialog asking finally
accepted. `JOE_DATAPOINTS=0` writes none; nothing deletes them.

See [docs/api.md](docs/api.md) for the full API endpoint reference.

### Python setup

`uv.lock` is the one source of truth for Python dependencies; `uv sync`
installs them and `uv run` runs inside that environment.

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
uv run pytest -q
```

Run frontend E2E tests:

```powershell
npm run test:e2e
```

Run backend pipeline:

```powershell
uv run joe run
```

Expected artifacts are created under `Data/Output/<timestamp>/`:

- `Data/Output/<timestamp>/Chroma/*.png`
- `Data/Output/<timestamp>/MIDI/*.mid`
- `Data/Output/<timestamp>/Process_Data_<timestamp>.json`

Input audio is read from `Data/Audio/`.

## Project Structure

- `Data/`: input audio and generated outputs (git-ignored)
- `Modules/`: core Python classes — the pipeline's (`Audio`, `Chroma`, `MIDI`, `Note`, utilities; see [docs/modules.md](docs/modules.md)) and the speech engine's (`Voice` for capture and transcription, `Conversation` for the turn the page shows)
- `src/`: frontend source (`p5.js` + Vite) — components, config, sketch
- `tests/`: Python unit tests; `tests/e2e/` for Playwright E2E tests
- `docs/`: contributor guide, module reference, API reference
- `api.py`: FastAPI server — the pipeline's routes and the speech engine's `/api/voice/*` routes; see [docs/api.md](docs/api.md)
- `cli.py`: Typer CLI (`joe frontend | backend | dev | run | voice setup | voice listen | voice transcribe | voice devices | voice level`)
- `main.py`: backend pipeline entrypoint

## Frontend Architecture

The Vite frontend (`src/`) has three layers:

- **FFT canvas** — `src/sketch.js` runs a live mic FFT visualiser via `p5.AudioIn` + `p5.FFT`. p5 and p5.sound are loaded as CDN globals (not bundled via Vite) because p5.sound must patch `window.p5` at script-evaluation time. Dot size scales on a dB curve (`20·log₁₀(v/255)`) to match human loudness perception.
- **Piano roll canvas** — `src/components/MainCanvas.js` overlays a full-screen canvas that runs in two modes: **LIVE** (real-time scrolling note detections from mic onset detection) and **RESULTS** (static pitch × time piano roll from pipeline JSON, coloured by transform type: Raw white, Harmonic cyan, Percussive orange).
- **Era panel** — `src/components/EraPanel.js` shows setlist metadata with arrow-key navigation and anime.js cross-fades.

### Bottom bar control groups

```text
[Joe, go!] | [Browser|Backend] [Live] [dot] | [LIVE|RESULTS] [Play] [Stop] [scrub] | [Library] [Results] | [Instruct by voice]
```

| Group | Controls | Notes |
| --- | --- | --- |
| Audio context | `Joe, go!` | One-time click — resumes Web Audio, enables Live |
| Live capture | mode select + `Live` + indicator | Browser = MediaRecorder mic; Backend = sounddevice WAV |
| Transport | mode badge + `Play/Stop` + scrub + `×` eject | Disabled while recording; badge shows `LIVE` or `RESULTS`; `×` clears active source |
| Panels | `Library` + `Results` | Slide-in panels for file management and analysis output |
| Voice | `Instruct by voice` | One spoken instruction into qmcp's inbox; the outcome shows in the voice panel |

See [docs/cookbook.md](docs/cookbook.md) for step-by-step recipes.

> **Note:** `npm run build` warns that `outDir` is outside the project root — expected (Vite root is `src/`).

## Docs

| Document | Contents |
| --- | --- |
| [docs/contributing.md](docs/contributing.md) | Local setup, UI control groups, troubleshooting, branch naming, pre-PR checks |
| [docs/cookbook.md](docs/cookbook.md) | Step-by-step recipes for common workflows |
| [docs/api.md](docs/api.md) | FastAPI endpoint reference with `curl` examples |
| [docs/modules.md](docs/modules.md) | Python module architecture and data flow |

## Contributing

See [docs/contributing.md](docs/contributing.md) for branch naming, required checks, and PR expectations.
