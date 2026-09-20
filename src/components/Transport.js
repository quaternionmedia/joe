/**
 * Transport — playback controls linked to MainCanvas.
 *
 * Owns an HTMLAudioElement.  setFile(name, url) loads a file and enables
 * play/pause/stop and scrubbing.  Each animation frame while playing,
 * MainCanvas.setPlayhead() is called with audio.currentTime so the
 * playhead stays in sync.
 *
 * Exactly one audio source can be active at a time.
 * clearFile() ejects the current source and dispatches joe:audioCleared.
 * setFile() dispatches joe:audioDurationKnown once metadata is ready.
 */
export class Transport {
  /**
   * @param {HTMLElement} el        - #transport element
   * @param {MainCanvas}  mainCanvas
   */
  constructor(el, mainCanvas) {
    this._el      = el;
    this._mc      = mainCanvas;
    this._audio   = new Audio();
    this._raf     = null;
    this._onScrub = null;   // optional override; receives raw scrubber value

    this._audio.onended = () => {
      this._setPlayBtn('Play');
      cancelAnimationFrame(this._raf);
    };
    this._name = '';
  }

  mount() {
    const q = s => this._el.querySelector(s);
    q('[data-testid="transport-play"]')
      .addEventListener('click', () => this.togglePlay());
    q('[data-testid="transport-stop"]')
      .addEventListener('click', () => this.stop());
    q('[data-testid="transport-scrub"]')
      .addEventListener('input', e => {
        const v = parseFloat(e.target.value);
        if (this._onScrub) {
          this._onScrub(v);   // live-frame scrub override
        } else {
          this._audio.currentTime = v;
          this._mc.setPlayhead(v);
          this._updateTime(v);
        }
      });
    const ejectBtn = q('[data-testid="transport-eject"]');
    if (ejectBtn) ejectBtn.addEventListener('click', () => this.clearFile());
  }

  /**
   * Load an audio file and update the transport UI.
   * @param {string} name - display filename
   * @param {string} url  - audio source URL
   */
  setFile(name, url) {
    this._name  = name;
    this._audio.src = url;
    this._audio.load();
    const q = s => this._el.querySelector(s);
    q('[data-testid="transport-name"]').textContent = name;
    this._audio.onloadedmetadata = () => {
      const dur = this._audio.duration || 0;
      q('[data-testid="transport-scrub"]').max = dur;
      q('[data-testid="transport-duration"]').textContent = this._fmt(dur);
      document.dispatchEvent(new CustomEvent('joe:audioDurationKnown', {
        detail: { name, duration: dur },
      }));
    };
    // Reset UI immediately — scrub.max must be cleared before metadata arrives
    // so a stale range from live-scrub mode doesn't let the user seek to
    // impossibly large timestamps (e.g. frame-count seconds).
    this._mc.setPlayhead(0);
    this._setPlayBtn('Play');
    this._updateScrub(0);
    this._updateTime(0);
    q('[data-testid="transport-scrub"]').max = 0;
    q('[data-testid="transport-duration"]').textContent = '…';
    const eject = this._el.querySelector('[data-testid="transport-eject"]');
    if (eject) eject.hidden = false;
  }

  /**
   * Eject the current audio source and reset the transport to an idle state.
   * Dispatches joe:audioCleared so index.js can tear down FFT routing and
   * clear the library active-file indicator.
   */
  clearFile() {
    this._audio.pause();
    this._audio.src = '';
    this._name = '';
    this._audio.onloadedmetadata = null;
    cancelAnimationFrame(this._raf);
    this._mc.setPlayhead(0);
    this._setPlayBtn('Play');
    this._updateScrub(0);
    this._updateTime(0);
    const q = s => this._el.querySelector(s);
    q('[data-testid="transport-name"]').textContent = '';
    q('[data-testid="transport-duration"]').textContent = '0:00';
    q('[data-testid="transport-scrub"]').max = 100;
    const eject = q('[data-testid="transport-eject"]');
    if (eject) eject.hidden = true;
    document.dispatchEvent(new CustomEvent('joe:audioCleared'));
  }

  play() {
    if (!this._audio.src) return;
    this._audio.play().catch(() => {});
    this._setPlayBtn('Pause');
    const tick = () => {
      const t = this._audio.currentTime;
      this._mc.setPlayhead(t);
      this._updateScrub(t);
      this._updateTime(t);
      if (!this._audio.paused && !this._audio.ended) {
        this._raf = requestAnimationFrame(tick);
      }
    };
    this._raf = requestAnimationFrame(tick);
  }

  pause() {
    this._audio.pause();
    cancelAnimationFrame(this._raf);
    this._setPlayBtn('Play');
  }

  stop() {
    this._audio.pause();
    this._audio.currentTime = 0;
    this._mc.setPlayhead(0);
    cancelAnimationFrame(this._raf);
    this._setPlayBtn('Play');
    this._updateScrub(0);
    this._updateTime(0);
  }

  togglePlay() {
    this._audio.paused ? this.play() : this.pause();
  }

  get isPlaying()    { return !this._audio.paused; }
  get currentTime()  { return this._audio.currentTime; }
  get audioElement() { return this._audio; }

  /**
   * Set a scrubber override callback (live-frame mode).
   * When set, scrub input calls fn(value) instead of seeking the audio element.
   * Set to null to restore normal audio-time behaviour.
   */
  set onScrub(fn) { this._onScrub = fn; }

  /**
   * Configure the scrubber range for non-audio use (e.g. live-frame scrubbing).
   * @param {number} max           - scrubber max value
   * @param {string} durationLabel - text shown in duration display
   */
  configureScrub(max, durationLabel) {
    const q = s => this._el.querySelector(s);
    q('[data-testid="transport-scrub"]').max   = max;
    q('[data-testid="transport-scrub"]').value = max;
    q('[data-testid="transport-duration"]').textContent = durationLabel;
    this._updateTime(0);
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  _updateScrub(t) {
    this._el.querySelector('[data-testid="transport-scrub"]').value = t;
  }

  _updateTime(t) {
    this._el.querySelector('[data-testid="transport-time"]').textContent = this._fmt(t);
  }

  _setPlayBtn(label) {
    this._el.querySelector('[data-testid="transport-play"]').textContent = label;
  }

  _fmt(t) {
    if (!isFinite(t) || isNaN(t)) return '0:00';
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }
}
