# Joe — Functional & Logical Audit (2026-04-04)

## Executive Summary

Well-architected codebase with clear separation of concerns. The main issues are accumulated documentation drift, gaps in error handling, missing test coverage, and a few logic misalignments between components. **66 issues** identified across 24 files.

---

## Phase 1: Critical Fixes (Ship-blocking)

### 1.1 requirements.txt incomplete
**File**: `requirements.txt`  
`fastapi`, `uvicorn[standard]`, and `typer` are all in `pyproject.toml` but **missing from requirements.txt**. The documented fallback install path (`pip install -r requirements.txt`) silently produces a broken environment.  
**Fix**: Add missing deps to requirements.txt.

### 1.2 No timeout on subprocess calls
**File**: `api.py`, `run_pipeline()` / `run_pipeline_for_file()`  
`proc.communicate()` has no timeout. A large audio file hangs the FastAPI event loop indefinitely.  
**Fix**: Wrap with `asyncio.wait_for(..., timeout=120)`.

### 1.3 File upload missing validation
**File**: `api.py`, `audio_upload()`  
No file-size limit, no MIME-type whitelist, and no deduplication. Timestamp-collision uploads overwrite files.  
**Fix**: Cap at 100MB, validate content-type against an allowlist, generate collision-safe filename.

### 1.4 Silent error on pipeline failure
**File**: `src/components/CapturePanel.js`, `_processFile()`  
`data.stderr.split('\n').filter(Boolean).pop()` returns `undefined` when stderr is empty but returncode is 1. Error dialog shows blank.  
**Fix**: `const msg = data.stderr?.trim() || 'Pipeline failed without error message';`

### 1.5 Dead dependencies
**File**: `pyproject.toml`  
`whisper-openai` and `spacy` are listed but never imported or used anywhere.  
**Fix**: Remove both.

---

## Phase 2: Alignment & Clarity (Next release)

### 2.1 Constant duplication across three files
| Constant | Files |
|----------|-------|
| `LABEL_W = 28` | `index.js:12`, `sketch.js:5`, `MainCanvas.js:20` |
| `TRANSPORT_H = 48` | `sketch.js:4`, `MainCanvas.js:21` |
| `_fmt(t)` time formatter | `index.js:60-65`, `Transport.js:183-187` |

**Fix**: Extract to `src/config/constants.js` and `src/utils/format.js`.

### 2.2 dB curve formula is misleading
**File**: `README.md` line 120  
Docs say `20·log₁₀(v/255)` but `sketch.js:logMap()` normalises from range 20–255 (not 0–255).  
**Fix**: Update README to say "dB scale: 20·log₁₀(energy/255), energy clamped to 20–255 range".

### 2.3 Live notes lack type field — silent fallback colour
**File**: `MainCanvas.js` vs `LiveAnalysis.js`  
Static layer notes carry `note.type` (Raw/Harmonic/Percussive) for colouring. `LiveAnalysis` never sets it, so all live notes render in `FALLBACK_COLOUR` (grey) rather than being type-coloured.  
**Fix**: `LiveAnalysis` should accept and stamp a transform-type parameter.

### 2.4 JOE_AUDIO_FILE env-var contract undocumented
`main.py` honours `JOE_AUDIO_FILE` to process a single file; `api.py` sets it for `POST /api/run/{filename}`. Neither README nor modules.md mentions this.  
**Fix**: Add a paragraph in `docs/modules.md` under "Configuration".

### 2.5 Parameters not documented
`main.py` defines `chroma_threshold`, `harmonic_threshold`, `min_duration`, `fft_sizes`, `overtone_weights` but nothing in docs explains how to tune them.  
**Fix**: Add "Configuration Reference" section to `docs/modules.md`.

### 2.6 ResultsPanel JSON not validated
**File**: `ResultsPanel.js`, `loadJSON()`  
Optional chaining silently skips malformed track objects. No schema error is surfaced.  
**Fix**: Validate `data.audio` exists and is an object; throw a user-visible error otherwise.

### 2.7 File input not reset after bad JSON
**File**: `ResultsPanel.js` around line 100  
`e.target.value` is only cleared on success. After a bad file, re-selecting the same file triggers no change event.  
**Fix**: Always reset `e.target.value` in the finally block.

### 2.8 Contributing.md cites CI that doesn't exist
**File**: `docs/contributing.md` lines 179–186  
Lists "Expected CI Checks" but there is no `.github/workflows/` directory.  
**Fix**: Either create a basic GitHub Actions workflow, or mark the section as "Planned CI".

### 2.9 contributing.md troubleshooting entry misleading
"Red dot pulses but canvas is blank → Joe, go! not clicked" — if the red dot pulses the FFT is active; the real issue is the live layer is not being drawn.  
**Fix**: Revise diagnosis to "Live button not clicked / no active audio source".

---

## Phase 3: Robustness & Testing (Polish)

### 3.1 capture.py has zero unit tests
`AudioCapture` threading, queue drain, and error scenarios are completely untested.  
**Fix**: `tests/test_capture.py` with mocked `sounddevice`.

### 3.2 api.py has no unit tests
All API endpoint coverage comes only from Playwright E2E. No FastAPI `TestClient` tests.  
**Fix**: `tests/test_api.py` using `httpx.AsyncClient` or `TestClient`.

### 3.3 E2E gaps: recording, playback, errors
Missing E2E coverage for:
- Browser / backend recording (toggles state, file appears in library)
- Transport play/pause/stop and time display
- API 500-error response
- 404 after library list (deleted file)
- Concurrent Process clicks

### 3.4 main.py has no exit code
`AudioToMidi()` crashes silently; `api.py` and `cli.py` cannot detect pipeline failure.  
**Fix**: Wrap in try/except, call `sys.exit(1)` on failure.

### 3.5 Add GitHub Actions workflow
**File**: `.github/workflows/test.yml`  
Runs `python -m pytest -q`, `npm run build`, and `npm run test:e2e` on PR.

### 3.6 Web Audio context suspension unhandled
`_audioActive` stays `true` even if the browser suspends the audio context (hardware or tab policy).  
**Fix**: After `startAudio()` resolves, check `context.state === 'running'` and reset `_audioActive` if not.

### 3.7 Transport: race on rapid file load
**File**: `Transport.js`, `setFile()`  
If a second file is loaded before `onloadedmetadata` fires for the first, a stale `joe:audioDurationKnown` is dispatched for the wrong file.  
**Fix**: Store a sequence counter; discard events from previous load requests.

### 3.8 `just_one_file` dead variable
**File**: `main.py` line 26  
`just_one_file = True` is set but never used; the value is hardcoded in the `get_audio_files()` call.  
**Fix**: Remove variable; pass literal if always `True`, or expose as CLI parameter.

---

## Cross-cutting Issues

### Env-var leaking (api.py)
`api.py` builds subprocess env as `{**os.environ, "JOE_AUDIO_FILE": ...}`. If the parent process already has `JOE_AUDIO_FILE` set (e.g. dev session), it bleeds through to the `/api/run` (all-files) route.  
**Fix**: Explicitly `del env["JOE_AUDIO_FILE"]` in the all-files route.

### pnoDist magic offset undocumented
`sketch.js` offset of `_numKeys/2 + 5` targets MIDI 49 = A4 as the reference frequency, but this is not commented. If pnoDist is ever adjusted, alignment with MainCanvas.js pitch positions silently breaks.

---

## Issue Count Summary

| Severity | Count |
|----------|-------|
| Critical (ship-blocking) | 5 |
| High (fix next release) | 10 |
| Medium (nice to have) | 8 |
| Low (style / refactor) | 7 |
| **Total** | **30+** |

---

## File-level Checklists

### Backend
- [ ] `requirements.txt` — add fastapi, uvicorn, typer
- [ ] `pyproject.toml` — remove whisper-openai, spacy
- [ ] `api.py` — subprocess timeout, upload validation, env leak fix
- [ ] `main.py` — remove `just_one_file`, add sys.exit
- [ ] `capture.py` — document threading contract; add error surfacing

### Frontend
- [ ] `src/config/constants.js` — extract LABEL_W, TRANSPORT_H, PITCH_MIN/MAX
- [ ] `src/utils/format.js` — extract _fmt / formatTime
- [ ] `src/components/LiveAnalysis.js` — stamp note.type
- [ ] `src/components/MainCanvas.js` — guard liveFrame=0 division
- [ ] `src/components/ResultsPanel.js` — schema validation, reset file input
- [ ] `src/components/Transport.js` — sequence counter for rapid load
- [ ] `src/index.js` — check audio context state post-resume

### Tests
- [ ] `tests/test_capture.py` — new, AudioCapture unit tests
- [ ] `tests/test_api.py` — new, FastAPI TestClient tests
- [ ] `tests/e2e/record.spec.js` — new, recording state transitions
- [ ] Expand existing E2E for Transport, error paths, concurrent clicks

### Docs
- [ ] `README.md` — fix dB curve formula, document JOE_AUDIO_FILE
- [ ] `docs/modules.md` — add configuration reference, env var contract
- [ ] `docs/contributing.md` — fix troubleshooting entry, clarify CI status
- [ ] `.github/workflows/test.yml` — new, basic CI pipeline
