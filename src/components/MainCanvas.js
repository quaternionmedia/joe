/**
 * MainCanvas — unified full-screen piano roll renderer.
 *
 * Two rendering layers composited on one canvas:
 *   Static — pipeline analysis notes (time-pitch, with a scrubable playhead)
 *   Live   — scrolling real-time notes from mic FFT onset detection;
 *            freezes on stopLive() and becomes scrubable via setLivePlayhead()
 *
 * The rAF loop runs continuously.  Whichever layers are active are drawn
 * each frame; idle frames just redraw the guide lines.
 *
 * Pitch range: MIDI 20 (A0, pnoDist key 0) → MIDI 107 (B7, pnoDist key 87).
 * Coordinate system matches sketch.js so the two canvases are pixel-aligned.
 */

const PITCH_MIN = 20;
const PITCH_MAX = 107;
const PITCH_RNG = PITCH_MAX - PITCH_MIN;   // 87

const LABEL_W      = 28;   // px reserved for pitch labels on the left
const TRANSPORT_H  = 48;   // px reserved for the transport bar at the bottom

const TYPE_COLOURS = {
  Raw:        'rgba(255,255,255,0.80)',
  Harmonic:   'rgba(0,229,255,0.80)',
  Percussive: 'rgba(255,109,0,0.80)',
};
const FALLBACK_COLOUR    = 'rgba(170,170,170,0.70)';
const C_LINE_COLOUR      = 'rgba(255,255,255,0.08)';
const LABEL_COLOUR       = 'rgba(255,255,255,0.22)';
const PLAYHEAD_COLOUR    = 'rgba(255,255,255,0.65)';
const NOW_LINE_COLOUR    = 'rgba(255,255,255,0.30)';
const LIVE_DONE_COLOUR   = 'rgba(255,255,255,0.45)';
const LIVE_ACTIVE_COLOUR = 'rgba(255,255,255,0.85)';

const LIVE_WINDOW = 300;   // sketch frames visible across the draw area

export class MainCanvas {
  /** @param {HTMLCanvasElement} el */
  constructor(el) {
    this._canvas = el;
    this._ctx    = el.getContext('2d');

    // Static layer
    this._notes    = [];
    this._totalDur = 0;
    this._playhead = 0;   // seconds

    // Live layer
    this._liveActive      = false;
    this._liveFrame       = 0;
    this._livePlayhead    = 0;   // frame index for frozen scrubbing
    this._liveNotes       = [];
    this._liveActiveNotes = [];
    this._liveDuration    = 0;   // seconds; set after recording so notes align with audio

    this._resize();
    window.addEventListener('resize', () => this._resize());
    this._tick();
  }

  // ─── Static layer API ───────────────────────────────────────────────────

  /** Load pipeline analysis notes.  Resets playhead to 0. */
  loadNotes(notes) {
    this._notes    = notes;
    this._totalDur = notes.length
      ? Math.max(...notes.map(n => n.start_time + n.duration))
      : 0;
    this._playhead = 0;
  }

  clearNotes() {
    this._notes    = [];
    this._totalDur = 0;
    this._playhead = 0;
  }

  /** Total duration of loaded notes in seconds (0 if nothing loaded). */
  get totalDuration() { return this._totalDur; }

  /** Move the playhead to t seconds (clamped). Called by Transport each rAF. */
  setPlayhead(t) {
    this._playhead = Math.max(0, Math.min(t, this._totalDur || 0));
  }

  // ─── Live layer API ─────────────────────────────────────────────────────

  startLive() {
    this._liveFrame       = 0;
    this._livePlayhead    = 0;
    this._liveNotes       = [];
    this._liveActiveNotes = [];
    this._liveActive      = true;
  }

  /** @param {Array} notes       - completed notes from LiveAnalysis.getNotes()
   *  @param {Array} activeNotes - in-progress notes from LiveAnalysis.getActive() */
  tickLive(notes, activeNotes) {
    this._liveNotes       = notes;
    this._liveActiveNotes = activeNotes || [];
    this._liveFrame++;
  }

  /** Freeze the live layer.  scrubber can now call setLivePlayhead(). */
  stopLive() {
    this._liveActive   = false;
    this._livePlayhead = this._liveFrame;   // start at end ("now")
  }

  /**
   * Set the known duration (seconds) of the recorded audio so the frozen
   * live layer can be drawn on the same time axis as the static results layer.
   * Call this once the audio element fires loadedmetadata.
   * @param {number} secs
   */
  setLiveDuration(secs) {
    this._liveDuration = secs;
  }

  /** Total frame count of the frozen live recording (0 if not yet recorded). */
  get liveFrameCount() { return this._liveFrame; }

  /**
   * Move the live-layer view to a given frame (frozen mode only).
   * Driven by the transport scrubber while no audio file is loaded.
   * @param {number} frame
   */
  setLivePlayhead(frame) {
    this._livePlayhead = Math.max(0, Math.min(frame, this._liveFrame));
  }

  // ─── Rendering ──────────────────────────────────────────────────────────

  _resize() {
    this._canvas.width  = window.innerWidth;
    this._canvas.height = window.innerHeight - TRANSPORT_H;
  }

  _tick() {
    this._render();
    requestAnimationFrame(() => this._tick());
  }

  /** Map MIDI pitch to canvas Y (high pitch = top). Matches sketch.js formula. */
  _pitchY(pitch) {
    return ((PITCH_MAX - pitch) / PITCH_RNG) * this._canvas.height;
  }

  _render() {
    const { _canvas: canvas, _ctx: ctx } = this;
    const W     = canvas.width;
    const H     = canvas.height;
    const drawW = W - LABEL_W;
    const rowH  = H / PITCH_RNG;

    ctx.clearRect(0, 0, W, H);

    // ── C-note guide lines — thin hairlines at octave boundaries ─────────
    ctx.font        = '9px Courier New';
    ctx.textAlign   = 'right';
    ctx.strokeStyle = C_LINE_COLOUR;
    ctx.lineWidth   = 0.5;
    for (let p = PITCH_MIN; p <= PITCH_MAX; p++) {
      if (p % 12 !== 0) continue;   // C notes only
      const y = this._pitchY(p);
      ctx.beginPath();
      ctx.moveTo(LABEL_W, y);
      ctx.lineTo(W, y);
      ctx.stroke();
      ctx.fillStyle = LABEL_COLOUR;
      ctx.fillText(`C${Math.floor(p / 12) - 1}`, LABEL_W - 3, y + rowH * 0.75);
    }

    // ── Static layer — pipeline analysis notes + playhead ────────────────
    // Hidden while live layer is active to avoid axis-mismatch confusion.
    if (!this._liveActive && this._notes.length) {
      const dur  = this._totalDur || 1;
      const barH = Math.max(2, rowH * 0.7);
      for (const note of this._notes) {
        const x  = LABEL_W + (note.start_time / dur) * drawW;
        const bw = Math.max(2, (note.duration  / dur) * drawW);
        const y  = this._pitchY(note.pitch) + (rowH - barH) / 2;
        ctx.fillStyle = TYPE_COLOURS[note.type] || FALLBACK_COLOUR;
        ctx.fillRect(x, y, bw, barH);
      }

      // Dashed playhead — scrubbed by Transport
      if (this._totalDur > 0) {
        const px = LABEL_W + (this._playhead / this._totalDur) * drawW;
        ctx.save();
        ctx.strokeStyle = PLAYHEAD_COLOUR;
        ctx.lineWidth   = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, H);
        ctx.stroke();
        ctx.restore();
      }
    }

    // ── Live layer — active recording OR frozen scrub OR overlay ─────────
    // Shown when: (a) actively recording, or (b) recording is frozen.
    // When _liveDuration > 0 and results are present, notes are drawn on
    // the shared time axis as a dimmed overlay so they align with the static layer.
    const showLive = this._liveActive || this._liveNotes.length > 0;

    if (showLive) {
      const barH      = Math.max(2, rowH * 0.7);
      const rightEdge = LABEL_W + drawW;

      // Overlay mode: results are present → suppress frame-scroll view so the
      // static results layer is immediately visible.  Once _liveDuration is set
      // (after audio metadata loads) the live notes are drawn on the shared time
      // axis as a dimmed underlay.  Without _liveDuration we still stay in
      // overlay mode — we just skip rendering the live notes until we have the
      // frame→seconds mapping.
      const overlayMode = !this._liveActive
        && this._notes.length > 0
        && this._liveFrame > 0;

      if (overlayMode) {
        if (this._liveDuration > 0) {
          const dur        = this._totalDur || 1;
          const frameToSec = this._liveDuration / this._liveFrame;
          ctx.fillStyle    = 'rgba(255,255,255,0.18)';
          for (const note of this._liveNotes) {
            const startSec = note.start * frameToSec;
            const durSec   = note.duration * frameToSec;
            const x  = LABEL_W + (startSec / dur) * drawW;
            const bw = Math.max(2, (durSec / dur) * drawW);
            const y  = this._pitchY(note.pitch) + (rowH - barH) / 2;
            ctx.fillRect(x, y, bw, barH);
          }
        }
        // Static layer's playhead covers both; no separate hairline needed.

      } else {
        // Scrolling (active) or frozen frame-scrub mode.
        const viewFrame = this._liveActive ? this._liveFrame : this._livePlayhead;

        // "Now" hairline at the right edge
        ctx.save();
        ctx.strokeStyle = NOW_LINE_COLOUR;
        ctx.lineWidth   = 1;
        ctx.setLineDash([2, 6]);
        ctx.beginPath();
        ctx.moveTo(rightEdge, 0);
        ctx.lineTo(rightEdge, H);
        ctx.stroke();
        ctx.restore();

        // Frozen mode: dashed playhead showing position within the recording
        if (!this._liveActive && this._liveFrame > 0) {
          const frac = this._livePlayhead / this._liveFrame;
          const px   = LABEL_W + frac * drawW;
          ctx.save();
          ctx.strokeStyle = PLAYHEAD_COLOUR;
          ctx.lineWidth   = 1.5;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(px, 0);
          ctx.lineTo(px, H);
          ctx.stroke();
          ctx.restore();
        }

        // Completed notes — rendered relative to viewFrame
        ctx.fillStyle = LIVE_DONE_COLOUR;
        for (const note of this._liveNotes) {
          const ageStart = viewFrame - note.start;
          if (ageStart < 0 || ageStart > LIVE_WINDOW) continue;
          const x  = rightEdge - (ageStart / LIVE_WINDOW) * drawW;
          const bw = Math.max(2, (note.duration / LIVE_WINDOW) * drawW);
          const y  = this._pitchY(note.pitch) + (rowH - barH) / 2;
          ctx.fillRect(x, y, bw, barH);
        }

        // Active notes — only meaningful in live mode
        if (this._liveActive) {
          ctx.fillStyle = LIVE_ACTIVE_COLOUR;
          for (const note of this._liveActiveNotes) {
            const ageStart = viewFrame - note.start;
            if (ageStart < 0) continue;
            const x  = rightEdge - (ageStart / LIVE_WINDOW) * drawW;
            const bw = Math.max(2, rightEdge - x);
            const y  = this._pitchY(note.pitch) + (rowH - barH) / 2;
            ctx.fillRect(x, y, bw, barH);
          }
        }
      }
    }
  }
}
