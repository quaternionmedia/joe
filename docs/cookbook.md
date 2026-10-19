# Joe Cookbook

Practical user stories for common workflows. Each recipe assumes both servers are running
and the browser is open at `http://localhost:3000/joe`. joe has no authentication, so a
fresh joe serves only the media API ([security.md](security.md)).
`uv run joe dev --allow library` serves recipes 1 to 9, except recipe 4, which also needs
`--allow microphone`.

---

## Recipe 1 — Analyse an audio file you already have

**Goal:** Turn a WAV/MP3 into a piano roll and MIDI transcription.

1. Drop your file into `Data/Audio/`.
2. In a terminal:

   ```bash
   uv run joe run
   ```

3. In the browser, click **Results** (bottom-right) → **Fetch Latest**.

The piano roll shows Raw (white), Harmonic (cyan), and Percussive (orange) note layers.
To play the audio alongside the roll, open **Library** and click **Play** next to the file — the transport bar loads it and the playhead follows.

---

## Recipe 2 — Record live and watch note detection in real time

**Goal:** Play an instrument into the mic and see MIDI-like events appear as you play.

1. Make sure your browser mic is accessible (HTTPS or localhost).
2. Click **Joe, go!** — the button turns green and **Live** becomes enabled.
3. Select **Browser** in the capture mode selector (default).
4. Click **Live** — the red dot pulses and the canvas shows `LIVE`.
5. Play your instrument; onset detections scroll across the canvas in real time.
6. Click **Stop** when done.

The recording is saved automatically to `Data/Audio/`. Open **Library** to see it.

---

## Recipe 3 — Record then run the pipeline immediately

**Goal:** Capture a performance and get a full transcription in one flow.

1. Follow Recipe 2 steps 1–6 to record.
2. In **Library**, find the new file and click **Process**.
3. The pipeline runs; results load automatically and the canvas switches to `RESULTS` mode.
4. The transport bar loads the recording — click **Play** to replay it with the piano roll.

---

## Recipe 4 — Use backend (system audio) capture instead of browser

**Goal:** Record at higher quality via `sounddevice` (no browser compression).

**Needs:** `uv run joe dev --allow microphone --allow library`: the microphone to
record through the API, the library to play and process what it saved.

1. Select **Backend** in the capture mode selector in the transport bar.
2. Click **Joe, go!** then **Live** — this triggers `POST /api/capture/start`.
3. Play or route audio through your system device.
4. Click **Stop** — this flushes a WAV file to `Data/Audio/`.
5. Process via **Library → Process** or `curl -X POST http://localhost:8000/api/run/{filename}`.

**Requires:** `sounddevice` is installed (`uv sync` includes it via `pyproject.toml`).

---

## Recipe 5 — Load a previous result from disk

**Goal:** Review an old `Process_Data_*.json` without re-running the pipeline.

1. Click **Results** (bottom-right) to open the panel.
2. Click **Load JSON** and pick any `Process_Data_*.json` file from `Data/Output/`.

The piano roll renders immediately — no server required for this path.

---

## Recipe 6 — Upload an audio file via the API and process it

**Goal:** Automate intake and processing with `curl` (CI / scripting use case).

**Needs:** `--allow library` (or `JOE_ALLOW_LIBRARY=1` in the API's environment).

```bash
# Upload
curl -X POST http://localhost:8000/api/audio/upload \
  -H "Content-Type: audio/wav" \
  --data-binary @my_recording.wav

# Returns: {"filename": "capture_20240101_120000.wav"}

# Process
curl -X POST http://localhost:8000/api/run/capture_20240101_120000.wav

# Fetch result
curl http://localhost:8000/api/results/latest | python -m json.tool
```

---

## Recipe 7 — Browse and replay the audio library

**Goal:** Listen back to any captured file without re-running anything.

1. Click **Library** (bottom-right) to open the panel.
2. Click **Play** next to any file — the transport bar loads it and starts playback.
3. Use the **scrub bar** to jump around; the piano roll playhead follows.
4. Click **Process** to run the pipeline on that file and switch the canvas to results.

---

## Recipe 8 — Understanding the single audio source

Joe enforces **one active audio file at a time**. Every path that loads audio
converges on the same internal gate, which keeps FFT routing, the transport
scrubber, and the library highlight always in sync.

### The four loading paths

| Trigger | How it loads | Auto-plays? |
| ------- | ----------- | ----------- |
| Library → **Play** | dispatches `joe:audioReady` | yes |
| Record stops (browser/backend) | dispatches `joe:audioReady` | no (file ready for scrub) |
| Library → **Process** (pipeline finishes) | dispatches `joe:resultsReady` | no |
| CLI `joe run` + **Fetch Latest** (or **Load JSON**) | loads notes only (no audio path) | — |

All three audio paths flow through a single `_activateAudio(name, url)` call in
`index.js`. This function:

1. Ejects any previously loaded source
2. Calls `transport.setFile(name, url)`
3. Connects the audio element to the p5 FFT analyser (so playback dots light up)
4. Highlights the file in the Library panel
5. Exits live-scrub mode if active

### Ejecting the current source

Click the **×** button that appears next to the filename in the transport bar.
This stops playback, disconnects FFT routing, clears the transport display, and
removes the Library highlight. The piano roll notes remain until you load new
results or clear them manually.

### What "no audio" means

When no file is loaded the transport scrubber either:

- Does nothing (no recording, no file)
- Scrubs the **frozen live layer** frame-by-frame after a recording (before pipeline runs)

Once a real audio file is activated, the scrubber returns to normal audio-time mode.

---

## Recipe 9 — Record, analyse, replay in one flow

**Goal:** Capture a performance, run the pipeline, and immediately replay it
with the piano roll aligned to the audio.

1. Click **Joe, go!** → click **Live** → play your instrument.
2. Click **Stop** — the recording saves and auto-loads into the transport bar.
   The scrubber now lets you scan through the frozen live detection.
3. Open **Library**, click **Process** next to the new file.
4. The pipeline runs; results load automatically and the canvas switches to `RESULTS`.
5. The same audio file is re-activated — click **Play** to hear it while the piano roll plays.
6. The library row for that file shows a cyan highlight while it is the active source.

---

## Recipe 10 — Caption and analyse a video for an editor

**Goal:** Give a video editor (alfred) what joe hears in a clip: the words with
their times, for captions, and its beats, loudness, silences and waveform, for
cutting. No browser: this is joe as an engine, over HTTP.

1. Put ffmpeg on PATH, or name it:

   ```powershell
   $env:JOE_FFMPEG = "C:\Program Files\kdenlive\bin\ffmpeg.exe"
   ```

2. Start the API alone on a port alfred does not use (alfred has 8000), and
   check that joe is answering there. The media API needs no setting: it is
   all a fresh joe serves.

   ```powershell
   uv run uvicorn api:app --port 8010
   curl http://localhost:8010/openapi.json   # "title": "Joe API"
   ```

3. Upload the clip. Ask about it from here on by the answer's `media_id`:

   ```bash
   curl -X POST http://localhost:8010/api/media \
     -H "Content-Type: video/mp4" --data-binary @clip.mp4
   # {"media_id": "323be26e5105eb0a57ca72d44566409b", "duration": 2.005,
   #  "sample_rate": 48000, "channels": 1, "has_audio": true}
   ```

4. Ask for the words with their times, and for what the sound does:

   ```bash
   curl -X POST "http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b/transcribe"
   curl -X POST "http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b/analyze?features=beats,loudness,silence"
   ```

5. Delete it when done, or leave it: an upload goes an hour after its last use
   (`JOE_MEDIA_TTL`).

   ```bash
   curl -X DELETE http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b
   ```

Every time in the answers is a time in the clip. A clip with no sound track is
refused with a 422, not kept. [media.md](media.md) has every field, the settings
and the errors.

---

## How the bottom bar controls relate

```text
[Joe, go!] [Browser|Backend] [Live] [●]   [LIVE|RESULTS] [Play] [Stop] [━━] 0:00/0:00 filename ×   [Library] [Results]
    │              │            │                │             │                        │
    │         Sets capture      │           Canvas mode        │                  Eject (×) clears
    │         mode for Live     │           badge              │                  the active source
    │              │            │                │             │
    └─ Enables Live after ──────┘           Changes to         └─ Transport play/stop
       first click (user gesture           LIVE when Live          disabled while Live
       required for Web Audio)             starts; RESULTS         recording is active
                                           when notes load
```

- **Joe, go!** resumes the Web Audio context — required once per page load before Live works.
- **Browser / Backend** selector sets where the captured audio comes from.
- **Live** starts/stops real-time recording. Disables Play/Stop while active.
- **Play / Stop** controls recorded-file playback. Disabled while Live is recording.
- **×** (eject) clears the active audio source. Appears only when a file is loaded.
- **Library** panel: browse, play, and process saved audio files. The active file is highlighted in cyan.
- **Results** panel: fetch or load pipeline JSON output; displays note metadata.
