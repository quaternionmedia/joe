/**
 * PianoRoll — 2D canvas renderer for extracted MIDI note events.
 *
 * Layout:
 *   X axis — time (sample units, scaled to canvas width)
 *   Y axis — MIDI pitch, high pitch at top (piano convention)
 *
 * Colour per transform type:
 *   Raw        → #ffffff  (white)
 *   Harmonic   → #00e5ff  (cyan)
 *   Percussive → #ff6d00  (orange)
 */

const TYPE_COLOURS = {
  Raw:        '#ffffff',
  Harmonic:   '#00e5ff',
  Percussive: '#ff6d00',
};
const FALLBACK_COLOUR = '#aaaaaa';
const GUIDE_LINE_COLOUR = 'rgba(255,255,255,0.07)';
const C_LINE_COLOUR     = 'rgba(255,255,255,0.18)';
const LABEL_COLOUR      = 'rgba(255,255,255,0.4)';
const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];

export class PianoRoll {
  /** @param {HTMLCanvasElement} canvasEl */
  constructor(canvasEl) {
    this._canvas = canvasEl;
    this._ctx    = canvasEl.getContext('2d');
  }

  /**
   * Render note events onto the canvas.
   * @param {Array<{ note: string, pitch: number, start_time: number, duration: number, type: string }>} notes
   */
  render(notes) {
    if (!notes || notes.length === 0) {
      this._showEmpty();
      return;
    }

    const w = this._canvas.offsetWidth  || 380;
    const h = this._canvas.offsetHeight || 300;
    this._canvas.width  = w;
    this._canvas.height = h;

    const ctx = this._ctx;

    const minPitch = Math.max(0,   Math.min(...notes.map(n => n.pitch)) - 2);
    const maxPitch = Math.min(127, Math.max(...notes.map(n => n.pitch)) + 2);
    const totalDur = Math.max(...notes.map(n => n.start_time + n.duration));
    const pitchRange = maxPitch - minPitch || 1;

    const LABEL_W = 28;
    const drawW   = w - LABEL_W;

    // Background
    ctx.fillStyle = 'rgba(0,0,0,0)';
    ctx.clearRect(0, 0, w, h);

    // Guide lines for every pitch row and highlighted C notes
    for (let pitch = minPitch; pitch <= maxPitch; pitch++) {
      const y = this._pitchToY(pitch, minPitch, maxPitch, h);
      const rowH = h / pitchRange;

      ctx.fillStyle = (pitch % 12 === 0) ? C_LINE_COLOUR : GUIDE_LINE_COLOUR;
      ctx.fillRect(LABEL_W, y, drawW, rowH);

      // Label every C and every 4 semitones
      if (pitch % 12 === 0 || pitch % 4 === 0) {
        const octave   = Math.floor(pitch / 12) - 1;
        const noteName = NOTE_NAMES[pitch % 12];
        ctx.fillStyle  = LABEL_COLOUR;
        ctx.font       = '9px Courier New';
        ctx.textAlign  = 'right';
        ctx.fillText(`${noteName}${pitch % 12 === 0 ? octave : ''}`, LABEL_W - 3, y + rowH * 0.75);
      }
    }

    // Note bars
    for (const note of notes) {
      const x = LABEL_W + (note.start_time / totalDur) * drawW;
      const bw = Math.max(2, (note.duration / totalDur) * drawW);
      const y  = this._pitchToY(note.pitch, minPitch, maxPitch, h);
      const bh = Math.max(2, h / pitchRange - 1);

      ctx.fillStyle = TYPE_COLOURS[note.type] || FALLBACK_COLOUR;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(x, y, bw, bh);
    }

    ctx.globalAlpha = 1;
  }

  clear() {
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
  }

  // ─── Private ───────────────────────────────────────────────────────────────

  _pitchToY(pitch, minPitch, maxPitch, h) {
    // High pitch = top → invert the mapping
    return ((maxPitch - pitch) / (maxPitch - minPitch || 1)) * h;
  }

  _showEmpty() {
    const w = this._canvas.offsetWidth  || 380;
    const h = this._canvas.offsetHeight || 300;
    this._canvas.width  = w;
    this._canvas.height = h;
    const ctx = this._ctx;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = LABEL_COLOUR;
    ctx.font      = '11px Courier New';
    ctx.textAlign = 'center';
    ctx.fillText('No notes found in this file.', w / 2, h / 2);
  }
}
