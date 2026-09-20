// p5 and p5.sound are CDN globals loaded in index.html
import './style.css';
import { createSketch } from './sketch.js';
import { EraPanel }     from './components/EraPanel.js';
import { ResultsPanel } from './components/ResultsPanel.js';
import { CapturePanel } from './components/CapturePanel.js';
import { MainCanvas }   from './components/MainCanvas.js';
import { Transport }    from './components/Transport.js';
import { setlist }      from './config/setlists.js';

// Must match MainCanvas.js LABEL_W — used for p5 playhead pixel calculation.
const LABEL_W = 28;

const state = { current: 0 };

// ─── p5 sketch ───────────────────────────────────────────────────────────────
// eslint-disable-next-line no-undef
const sketchInstance = new p5(createSketch(state), document.getElementById('sketch'));

// ─── Era panel ───────────────────────────────────────────────────────────────
const eraPanel = new EraPanel(document.getElementById('era-panel'), state, setlist);
eraPanel.mount();

// ─── Unified canvas + transport ──────────────────────────────────────────────
const mainCanvas = new MainCanvas(document.getElementById('piano-roll-canvas'));
const transport  = new Transport(document.getElementById('transport'), mainCanvas);
transport.mount();

// ─── Results panel ───────────────────────────────────────────────────────────
const resultsPanel = new ResultsPanel(document.getElementById('results-panel'), mainCanvas);
resultsPanel.mount();

// ─── Capture / library panel ─────────────────────────────────────────────────
const capturePanel = new CapturePanel(
  document.getElementById('capture-panel'),
  mainCanvas,
);
capturePanel.mount();

// ─── First-run hint ───────────────────────────────────────────────────────────
{
  const hintEl = document.getElementById('first-run-hint');
  if (localStorage.getItem('joe-hint-dismissed')) {
    hintEl.classList.add('hidden');
  }
  document.getElementById('hint-dismiss').addEventListener('click', () => {
    hintEl.classList.add('hidden');
    localStorage.setItem('joe-hint-dismissed', '1');
  });
}

// ─── Shared state ─────────────────────────────────────────────────────────────
let _audioActive     = false;
let _hasResults      = false;
let _syncRaf         = null;    // rAF handle for p5 playhead sync loop
let _activeAudioName = null;    // currently loaded audio filename (single source)

// ─── Helpers ──────────────────────────────────────────────────────────────────

function _fmt(t) {
  if (!isFinite(t) || isNaN(t)) return '0:00';
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

/**
 * Start syncing the p5 playhead hairline with Transport.currentTime.
 * Runs every rAF frame while results are displayed and audio may be playing.
 */
function _startPlayheadSync() {
  cancelAnimationFrame(_syncRaf);
  const sync = () => {
    if (_hasResults && mainCanvas.totalDuration > 0) {
      const norm = transport.currentTime / mainCanvas.totalDuration;
      sketchInstance.setPlayheadX(LABEL_W + norm * (window.innerWidth - LABEL_W));
    }
    _syncRaf = requestAnimationFrame(sync);
  };
  _syncRaf = requestAnimationFrame(sync);
}

/** Stop the p5 playhead sync and hide the hairline. */
function _stopPlayheadSync() {
  cancelAnimationFrame(_syncRaf);
  _syncRaf = null;
  sketchInstance.setPlayheadX(-1);
}

/**
 * Enter live-frame scrub mode after recording stops.
 * Wires the transport scrubber to scroll through the frozen live layer.
 * Estimated duration assumes ~60fps sketch frame rate.
 */
function _enterLiveScrubMode() {
  const frames  = mainCanvas.liveFrameCount;
  if (!frames) return;
  const estSecs = frames / 60;
  transport.onScrub = (frame) => {
    mainCanvas.setLivePlayhead(frame);
    document.querySelector('[data-testid="transport-time"]').textContent =
      _fmt(frame / 60);
  };
  transport.configureScrub(frames, _fmt(estSecs));
}

/** Restore normal audio-time scrub behaviour (called when results load). */
function _exitLiveScrubMode() {
  transport.onScrub = null;
}

/**
 * The single gateway for loading an audio source.
 * All paths that change the active audio file MUST call this function.
 * It ensures exactly one file is active at a time, keeps FFT routing
 * consistent, exits live-scrub mode, and notifies the library panel
 * which file is highlighted.
 *
 * @param {string} name - display filename
 * @param {string} url  - audio source URL
 */
function _activateAudio(name, url) {
  _activeAudioName = name;
  _exitLiveScrubMode();
  transport.setFile(name, url);
  // Connect audio element to p5 FFT (no-op if audio context not yet started;
  // the startBtn handler reconnects when the context resumes).
  if (_audioActive) sketchInstance.connectAudioSource(transport.audioElement);
  capturePanel.setActiveFile(name);
}

// ─── Bottom bar wiring ────────────────────────────────────────────────────────

const liveToggle    = document.getElementById('live-toggle');
const liveIndicator = document.getElementById('live-indicator');
const canvasModeEl  = document.getElementById('canvas-mode');
const captureMode   = document.getElementById('capture-mode');
const startBtn      = document.getElementById('start-button');

// Group 1 — audio context toggle
// First click: resumes Web Audio context + enables Live.
// Second click: suspends audio + re-disables Live (blocked while recording).
startBtn.addEventListener('click', () => {
  if (!_audioActive) {
    sketchInstance.startAudio();
    _audioActive = true;
    startBtn.textContent = 'Joe, stop!';
    startBtn.classList.add('active');
    liveToggle.disabled = false;
    // Re-connect audio element to FFT if a file was loaded before audio started.
    // startAudio() calls AudioContext.resume() asynchronously, so defer briefly.
    if (_activeAudioName) {
      setTimeout(() => sketchInstance.connectAudioSource(transport.audioElement), 100);
    }
  } else {
    if (capturePanel.isRecording) return;
    sketchInstance.disconnectAudioSource();
    sketchInstance.stopAudio();
    _stopPlayheadSync();
    _audioActive = false;
    startBtn.textContent = 'Joe, go!';
    startBtn.classList.remove('active');
    liveToggle.disabled = true;
  }
});

// Group 2a — capture mode selector (browser mic vs backend sounddevice)
captureMode.addEventListener('change', () => {
  capturePanel.setMode(captureMode.value);
});

// Group 2b — live record toggle
liveToggle.addEventListener('click', async () => {
  await capturePanel.toggleRecord();
});

// Sync bottom bar when recording state changes.
document.addEventListener('joe:captureState', (e) => {
  const rec = e.detail.recording;
  liveToggle.textContent = rec ? 'Stop' : 'Live';
  liveIndicator.classList.toggle('recording', rec);

  // Mutual exclusion — transport and Joe toggle disabled while recording
  document.querySelector('[data-testid="transport-play"]').disabled = rec;
  document.querySelector('[data-testid="transport-stop"]').disabled = rec;
  startBtn.disabled = rec;

  // Canvas mode badge
  canvasModeEl.textContent = rec ? 'LIVE' : '';
  canvasModeEl.classList.toggle('mode-live', rec);
  if (rec) {
    canvasModeEl.classList.remove('mode-results');
    _stopPlayheadSync();
    _exitLiveScrubMode();
  } else if (!_hasResults) {
    // Recording stopped, no results yet — enter live-frame scrub mode
    _enterLiveScrubMode();
  }
});

// Canvas mode badge + p5 playhead sync when notes are loaded.
document.addEventListener('joe:notesLoaded', () => {
  _hasResults = true;
  _exitLiveScrubMode();
  canvasModeEl.textContent = 'RESULTS';
  canvasModeEl.classList.add('mode-results');
  canvasModeEl.classList.remove('mode-live');
  _startPlayheadSync();
});

// Badge + p5 playhead hidden when notes are cleared.
document.addEventListener('joe:notesCleared', () => {
  _hasResults = false;
  _stopPlayheadSync();
  if (!capturePanel.isRecording) {
    canvasModeEl.textContent = '';
    canvasModeEl.classList.remove('mode-results', 'mode-live');
  }
});

// Group 4 — panel toggles
document.getElementById('capture-toggle')
  .addEventListener('click', () => capturePanel.toggle());
document.getElementById('results-toggle')
  .addEventListener('click', () => resultsPanel.toggle());

// ─── Frame pump — feeds sketch output into live analysis ─────────────────────
sketchInstance.onFrame = (energies) => {
  if (capturePanel.isRecording) capturePanel.pushFrame(energies);
};

// ─── Single audio source wiring ───────────────────────────────────────────────
//
// joe:audioReady  — fired by CapturePanel after upload, backend stop, or
//                   library "Play".  Routes through _activateAudio so the
//                   library highlight and FFT routing are always consistent.
document.addEventListener('joe:audioReady', (e) => {
  const { name, url, autoPlay } = e.detail;
  _activateAudio(name, url);
  if (autoPlay) transport.play();
});

// joe:audioDurationKnown — fired by Transport once onloadedmetadata resolves.
// Sets live-layer duration so frozen live notes align with the static results.
document.addEventListener('joe:audioDurationKnown', (e) => {
  mainCanvas.setLiveDuration(e.detail.duration);
});

// joe:audioCleared — fired by Transport.clearFile() (eject button).
// Tears down FFT routing and clears the library active-file highlight.
document.addEventListener('joe:audioCleared', () => {
  _activeAudioName = null;
  sketchInstance.disconnectAudioSource();
  capturePanel.setActiveFile(null);
  _stopPlayheadSync();
});

// ─── Pipeline completion ──────────────────────────────────────────────────────
// joe:resultsReady — fired by CapturePanel after pipeline run completes.
// Load notes into the canvas, then activate the corresponding audio file.
document.addEventListener('joe:resultsReady', async (e) => {
  await resultsPanel.fetchLatest();
  const name = e.detail?.filename;
  if (name) _activateAudio(name, `/api/audio/${encodeURIComponent(name)}`);
  resultsPanel.open();
});
