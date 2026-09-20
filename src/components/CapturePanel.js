/**
 * CapturePanel — Library panel for audio file management and capture settings.
 *
 * Recording is started/stopped externally via toggleRecord() (called from
 * the bottom bar live toggle).  State changes are broadcast via the
 * 'joe:captureState' CustomEvent so the bar can update its indicator.
 *
 * After any recording stops and the audio file is saved, a 'joe:audioReady'
 * CustomEvent is dispatched so index.js can immediately load the file into
 * Transport — making the scrubber and FFT routing available without the user
 * having to open the Library panel.
 *
 * Library "Play" also dispatches 'joe:audioReady' (with autoPlay: true) so
 * ALL audio loading routes through the central _activateAudio() in index.js.
 * CapturePanel never calls Transport directly.
 *
 * setActiveFile(name) is called by index.js to highlight the currently
 * loaded file in the library list.  Pass null to clear the highlight.
 *
 * Capture modes:
 *   Browser — MediaRecorder → .webm → POST /api/audio/upload
 *   Backend — POST /api/capture/start|stop → sounddevice .wav
 */

import { LiveAnalysis } from './LiveAnalysis.js';

export class CapturePanel {
  /**
   * @param {HTMLElement} el         - The #capture-panel element
   * @param {MainCanvas}  mainCanvas
   */
  constructor(el, mainCanvas) {
    this._el         = el;
    this._mainCanvas = mainCanvas;
    this._analysis   = new LiveAnalysis();
    this.isRecording = false;
    this._mode       = 'browser';
    this._lastFile   = null;
    this._mediaRecorder = null;
    this._chunks        = [];
    this._stream        = null;
  }

  /** Set capture mode from the transport bar selector. */
  setMode(mode) { this._mode = mode; }

  mount() {
    const q = s => this._el.querySelector(s);

    q('[data-testid="capture-process"]')
      .addEventListener('click', () => this._processFile(this._lastFile));
    q('[data-testid="capture-refresh"]')
      .addEventListener('click', () => this._loadLibrary());
    q('[data-testid="capture-close"]')
      .addEventListener('click', () => this.close());

    this._loadLibrary();
  }

  toggle() { this._el.classList.toggle('open'); }
  open()   { this._el.classList.add('open'); }
  close()  { this._el.classList.remove('open'); }

  /** Called by the bottom-bar Live toggle button. */
  async toggleRecord() {
    this.isRecording ? await this._stopRecord() : await this._startRecord();
  }

  /**
   * Feed one sketch draw frame into live analysis while recording.
   * @param {number[]|Float32Array} energies - 88 FFT energy values (0–255)
   */
  pushFrame(energies) {
    this._analysis.pushFrame(energies);
    this._mainCanvas.tickLive(this._analysis.getNotes(), this._analysis.getActive());
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  async _startRecord() {
    this.isRecording = true;
    this._lastFile   = null;
    this._analysis.reset();
    this._mainCanvas.startLive();
    this._notify();
    this._showFile(null);

    if (this._mode === 'backend') {
      const res  = await fetch('/api/capture/start', { method: 'POST' });
      const data = await res.json();
      this._lastFile = data.filename;
    } else {
      await this._startBrowserRecord();
    }
  }

  async _stopRecord() {
    this.isRecording = false;
    this._mainCanvas.stopLive();
    this._notify();

    if (this._mode === 'backend') {
      const res  = await fetch('/api/capture/stop', { method: 'POST' });
      const data = await res.json();
      this._lastFile = data.filename;
      this._showFile(data.filename);
      this._dispatchAudioReady(data.filename);
      await this._loadLibrary();
    } else {
      this._stopBrowserRecord();
    }
  }

  /** Dispatch state change so the bottom bar can update its indicator/label. */
  _notify() {
    document.dispatchEvent(
      new CustomEvent('joe:captureState', { detail: { recording: this.isRecording } })
    );
  }

  /**
   * Dispatch joe:audioReady so index.js can immediately load the file into
   * Transport — connecting audio playback and FFT routing without requiring
   * the user to open the Library panel.
   */
  _dispatchAudioReady(name) {
    document.dispatchEvent(new CustomEvent('joe:audioReady', {
      detail: { name, url: `/api/audio/${encodeURIComponent(name)}` },
    }));
  }

  // ─── Browser capture ─────────────────────────────────────────────────────

  async _startBrowserRecord() {
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error('[CapturePanel] Microphone access denied:', err);
      this.isRecording = false;
      this._notify();
      return;
    }
    this._chunks = [];
    this._mediaRecorder = new MediaRecorder(this._stream);
    this._mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) this._chunks.push(e.data);
    };
    this._mediaRecorder.start(100);
  }

  _stopBrowserRecord() {
    this._mediaRecorder.onstop = async () => {
      this._stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(this._chunks, { type: 'audio/webm' });
      try {
        const res  = await fetch('/api/audio/upload', {
          method:  'POST',
          body:    blob,
          headers: { 'Content-Type': 'audio/webm' },
        });
        const data = await res.json();
        this._lastFile = data.filename;
        this._showFile(data.filename);
        this._dispatchAudioReady(data.filename);   // ← auto-load into Transport
      } catch (err) {
        console.error('[CapturePanel] Upload failed:', err);
      }
      await this._loadLibrary();
    };
    this._mediaRecorder.stop();
  }

  // ─── Audio library ────────────────────────────────────────────────────────

  async _loadLibrary() {
    let files;
    try {
      const res = await fetch('/api/audio/files');
      files = await res.json();
    } catch {
      return;
    }

    const list = this._el.querySelector('[data-testid="capture-file-list"]');
    if (!files.length) {
      list.innerHTML = '<li class="lib-empty">No recordings yet.</li>';
      return;
    }

    list.innerHTML = files.map(f => {
      const kb = (f.size / 1024).toFixed(0);
      return `<li data-name="${f.name}">
        <span class="lib-name" title="${f.name}">${f.name}</span>
        <span class="lib-size">${kb} KB</span>
        <button data-action="play"    data-name="${f.name}" type="button">Play</button>
        <button data-action="process" data-name="${f.name}" type="button">Process</button>
      </li>`;
    }).join('');

    list.onclick = e => {
      const btn = e.target.closest('button[data-action]');
      if (!btn) return;
      if (btn.dataset.action === 'play')    this._playFile(btn.dataset.name);
      if (btn.dataset.action === 'process') this._processFile(btn.dataset.name);
    };
  }

  /**
   * Mark a library file as the active (loaded) source.
   * Called by index.js after _activateAudio(); pass null to clear.
   * @param {string|null} name
   */
  setActiveFile(name) {
    const list = this._el.querySelector('[data-testid="capture-file-list"]');
    list.querySelectorAll('li[data-name]').forEach(li => {
      li.classList.toggle('lib-active', li.dataset.name === name);
    });
  }

  _playFile(name) {
    // Route through index.js _activateAudio by dispatching joe:audioReady.
    // autoPlay: true starts playback once the file is loaded.
    document.dispatchEvent(new CustomEvent('joe:audioReady', {
      detail: { name, url: `/api/audio/${encodeURIComponent(name)}`, autoPlay: true },
    }));
  }

  async _processFile(name) {
    if (!name) return;
    this._showError('');
    try {
      const res  = await fetch(`/api/run/${encodeURIComponent(name)}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.returncode !== 0) {
        const lastLine = data.stderr?.split('\n').map(s => s.trim()).filter(Boolean).pop();
        const msg = lastLine || data.stderr?.trim() || 'Pipeline failed';
        this._showError(msg);
        console.error('[CapturePanel] Pipeline returned non-zero:', data.stderr);
        return;   // do NOT fire resultsReady — stale JSON stays hidden
      }
      document.dispatchEvent(new CustomEvent('joe:resultsReady', { detail: { filename: name } }));
    } catch (err) {
      this._showError(err.message || 'Network error');
      console.error('[CapturePanel] Pipeline trigger failed:', err);
    }
  }

  _showError(msg) {
    const el = this._el.querySelector('[data-testid="capture-error"]');
    if (!el) return;
    el.textContent = msg;
    el.hidden = !msg;
  }

  // ─── UI helpers ──────────────────────────────────────────────────────────

  _showFile(name) {
    const fileEl = this._el.querySelector('[data-testid="capture-file"]');
    fileEl.textContent = name ? `Saved: ${name}` : '';
    this._el.querySelector('[data-testid="capture-process"]').hidden = !name;
  }
}
