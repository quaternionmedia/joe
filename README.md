# Joe

> **joe has no authentication.** Whatever reaches its port is answered with
> your account's rights. Run it on one machine you trust, on loopback
> (`127.0.0.1`), where `joe backend`, `joe dev` and `uvicorn api:app` listen
> unless told otherwise. On any other address, everything that is on is open
> to whatever reaches it.
>
> **A fresh joe serves only the media API a video editor uses.** Each of the
> rest waits for a setting, and the server warns at startup for each one on:
>
> | To turn on | Set | Or, on `joe backend` |
> | --- | --- | --- |
> | Recording from the microphone | `JOE_ALLOW_MICROPHONE=1` | `--allow microphone` |
> | The transcripts of what was said | `JOE_ALLOW_TRANSCRIPTS=1` | `--allow transcripts` |
> | The audio library and pipeline | `JOE_ALLOW_LIBRARY=1` | `--allow library` |
>
> `joe dev`, for working on joe on this machine, turns every one on unless
> `--allow` names fewer. [docs/security.md](docs/security.md) is the threat
> model, and says which settings each program using joe needs.

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
uv run joe dev   # Vite :3000 + API on loopback :8000, every capability on
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
| `uv run joe backend [--allow CAPABILITY]` | FastAPI API server only (`127.0.0.1:8000`); the media API alone unless `--allow` turns on `microphone`, `transcripts`, `library` or `all` |
| `uv run joe dev [--allow CAPABILITY]` | Both servers (Ctrl+C to stop); the API on loopback with every capability on, or, given `--allow`, as `backend` starts it |
| `uv run joe run` | Run the pipeline once |
| `uv run joe voice setup` | **Start here for voice.** Find your microphone while you talk, save it, and prove it with a transcribed sentence |
| `uv run joe voice listen [--device N] [--fixed]` | Record until you stop talking, then transcribe (`--fixed` records the whole `--duration`) |
| `uv run joe voice transcribe <path>` | Transcribe an audio file to text |
| `uv run joe voice devices` | List audio input devices, with the host API that distinguishes same-named ones; `S` marks the saved microphone |
| `uv run joe voice level [--device N] [--every]` | How loud an input is right now |

**Voice, the first time:** run `uv run joe voice setup` and keep talking when
it says so. Once a test sentence has recorded from the microphone that heard
you, it saves that microphone to `Data/voice-device.json`, and every
recording — the CLI's and the backend's —
uses it from then on, with no environment variable to set and no restart.
`JOE_INPUT_DEVICE`, where set, still overrides it.

**Watching a conversation:** run `uv run joe dev`, which turns on the
microphone, for the backend to record, and the transcripts, for the page to
show what it heard. The page at `http://localhost:3000/joe`
then shows a voice panel whenever something is spoken through the backend:
asking, your turn, hearing you, pause, reading, and the answer. Each state
has its own colour, motion and label. The backend reports the microphone's
states itself; the program asking the question posts the rest
(`docs/api.md`, `/api/voice/conversation`).

**Answering by voice from the page:** with qmcp's server running as well
(`uv run python -m qmcp serve` in its checkout), whatever is waiting on you in
qmcp appears in the panel, oldest first, with **Answer by voice**. Pressing it
has qmcp ask the question aloud while joe's microphone hears the answer, and
the panel shows the turn as it happens. joe needs the microphone on for qmcp
to listen through it, and the transcripts for the panel; `joe dev` turns both
on. Nothing is spoken until the button is pressed. If the conversation cannot
start, the panel shows qmcp's own reason.
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
| `T` | opens or closes the Transcript |
| `L`, `A` | open or close the Library and the analysis Results |
| `Esc` | closes the Library, the Results and the Transcript |

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

**The whole transcript, beside the piano roll:** `T`, or the transport's
**Transcript** button, opens a window beside the piano roll holding everything said
in the exchange, oldest first -- each question as it was asked and each take
as it was heard, with its struck words crossed out, how sure the transcriber
was, whether it came by key or over the question, and how it was labelled.
It is read from joe's datapoints, so a reload keeps it, and extended live; it
follows the newest line unless scrolled back. **What can be said** lists the
conversation's words and checks and joe's own. The piano roll narrows to make
room for it.

**A take on the visualiser:** a take's **Show** plays its recording through the
transport and the spectrum, and lays its words along the bottom of the piano
roll at the times they were said, the word under the playhead lit and struck
words crossed out. joe knows when each segment of a take began and ended, so a
segment's words share its span evenly. Ejecting the recording, or loading a
pipeline result, takes the words away.

**The transcript as it is written:** a take is transcribed piece by piece
while it is spoken, and the panel shows the words as they arrive. Clicking a
word strikes it, or restores it; Backspace strikes the last word still
standing; saying "scratch that" strikes what came just before, and "start
over" the whole take. "Flag that" marks the last take misheard and "that was
right" marks it heard right, for tuning the recognition later; "how loud am I"
shows how far the voice cleared the threshold. The take's text
leaves struck words out, so what is read back is what the panel showed.

**Every piece is kept for tuning:** each stretch of speech is written as its
own WAV under `Data/Voice/segments/` and described in `Data/Voice/segments.jsonl`
-- its timing and levels, the hint and prompt it was decoded with, whisper's
own confidence, the text, the words struck, and what the dialog asking finally
accepted. `JOE_DATAPOINTS=0` writes none; nothing deletes them.

**The audio engine of a video editor:** alfred uploads a clip, or a
timeline's mixed sound, to `/api/media` and asks by id what is said in it
(each segment and word with its time, for captions) and how it moves: tempo,
beats, onsets, loudness (dBFS and LUFS), silences and a waveform's peaks. It
needs ffmpeg (on PATH, or named by `JOE_FFMPEG`) and no setting. Beside
alfred, which has port 8000, run the API alone:
`uv run uvicorn api:app --port 8010`. On loopback, alfred's containers reach
it on Docker Desktop but not on a Linux Docker host; joe has no
authentication, so mind what else can reach it before binding wider.
[docs/media.md](docs/media.md) is the reference: uploads and how long they
are kept, and running it on a Linux host.

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
python -m pytest -q
```

The media tests need ffmpeg and skip without it; name one with `JOE_FFMPEG`.
One runs the real whisper model when it is cached here;
`-m "not whisper_model"` leaves it out ([docs/media.md](docs/media.md#testing)).

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
- `Modules/`: core Python classes (`Audio`, `Chroma`, `MIDI`, `Note`, utilities), and `Media` and `Analysis` behind the media API — see [docs/modules.md](docs/modules.md)
- `src/`: frontend source (`p5.js` + Vite) — components, config, sketch
- `tests/`: Python unit tests; `tests/e2e/` for Playwright E2E tests
- `docs/`: contributor guide, module reference, API reference
- `api.py`: FastAPI server wrapping the pipeline — see [docs/api.md](docs/api.md)
- `cli.py`: Typer CLI (`joe frontend | backend | dev | run | voice setup | voice listen | voice transcribe | voice devices | voice level`)
- `main.py`: backend pipeline entrypoint

## Frontend Architecture

The Vite frontend (`src/`) is a dock of windows -- `src/layout/`, the
visualiser and every panel as windows of one GoldenLayout, described in
[docs/ui.md](docs/ui.md) -- and the visualiser has three layers:

- **FFT canvas** — `src/sketch.js` runs a live mic FFT visualiser via `p5.AudioIn` + `p5.FFT`. p5 and p5.sound are loaded as CDN globals (not bundled via Vite) because p5.sound must patch `window.p5` at script-evaluation time. Dot size scales on a dB curve (`20·log₁₀(v/255)`) to match human loudness perception.
- **Piano roll canvas** — `src/components/MainCanvas.js` draws over the FFT canvas, filling the visualiser's window, in two modes: **LIVE** (real-time scrolling note detections from mic onset detection) and **RESULTS** (static pitch × time piano roll from pipeline JSON, coloured by transform type: Raw white, Harmonic cyan, Percussive orange).
- **Era panel** — `src/components/EraPanel.js` shows setlist metadata with arrow-key navigation and anime.js cross-fades.

### Bottom bar control groups

```text
[Joe, go!] | [Browser mic|joe's mic] [Live] [dot] | [LIVE|RESULTS] [Play] [Stop] [scrub] | [Library] [Results] [Transcript] [▦] | [Instruct by voice]
```

| Group | Controls | Notes |
| --- | --- | --- |
| Audio context | `Joe, go!` | One-time click — resumes Web Audio, enables Live |
| Live capture | where Live records from + `Live` + indicator | **Browser mic** = this browser's microphone (MediaRecorder); **joe's mic** = the microphone of the machine joe runs on (sounddevice WAV) |
| Transport | mode badge + `Play/Stop` + scrub + `×` eject | Disabled while recording; badge shows `LIVE` or `RESULTS`; `×` clears active source |
| Windows | `Library` + `Results` + `Transcript` + `▦` | Each opens its window beside the visualiser, or closes it when it is in front; `▦`, the Panels menu, lists every window and resets the layout ([docs/ui.md](docs/ui.md)) |
| What is off | any of the above | The page reads `/api/health`: a control whose capability is off is greyed, its tooltip naming the setting, and its panel says so with a link to [docs/security.md](docs/security.md) |
| Voice | `Instruct by voice` | One spoken instruction into qmcp's inbox; the outcome shows in the voice panel |

Each user path, step by step, is a page in [docs/paths/](docs/paths/README.md).

> **Note:** `npm run build` warns that `outDir` is outside the project root — expected (Vite root is `src/`).

## Docs

| Document | Contents |
| --- | --- |
| [docs/paths/](docs/paths/README.md) | Each user path, step by step, with the spec or test that checks each step: the music page, the voice loop, and joe as a server |
| [docs/ui.md](docs/ui.md) | The page: its dock of windows, how they open, close and are kept, and what each holds |
| [docs/contributing.md](docs/contributing.md) | Local setup, UI control groups, troubleshooting, branch naming, pre-PR checks, what CI runs |
| [docs/api.md](docs/api.md) | FastAPI endpoint reference with `curl` examples |
| [docs/media.md](docs/media.md) | The media API a video editor uses: uploads, transcripts with word times, analysis |
| [docs/security.md](docs/security.md) | The threat model: what joe serves without authentication, the setting for each part, which each program using joe needs, and the review's findings |
| [docs/modules.md](docs/modules.md) | Python module architecture and data flow |

## Contributing

See [docs/contributing.md](docs/contributing.md) for branch naming, required checks, and PR expectations.
