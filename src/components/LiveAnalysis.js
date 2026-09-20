/**
 * LiveAnalysis — real-time per-pitch note onset detector.
 *
 * Mirrors the threshold-crossing logic in Modules/MIDI.py:calculate_note().
 * Fed one frame at a time from sketch.onFrame while recording is active.
 *
 * Usage:
 *   const analysis = new LiveAnalysis({ threshold: 25, minDuration: 5 });
 *   analysis.onNote(note => console.log(note));   // { pitch, start, duration }
 *   analysis.pushFrame(energies);                 // call each sketch frame
 *   const notes = analysis.getNotes();
 *   analysis.reset();
 */
export class LiveAnalysis {
  /**
   * @param {object} opts
   * @param {number} opts.threshold   - FFT energy (0–255) to trigger onset (default 25)
   * @param {number} opts.minDuration - Minimum frame count for a note to be recorded (default 5)
   */
  constructor({ threshold = 25, minDuration = 5 } = {}) {
    this._threshold = threshold;
    this._minDuration = minDuration;
    this._active = new Array(88).fill(null); // { startFrame } | null per pitch key
    this._notes = [];                        // completed { pitch, start, duration }
    this._frame = 0;
    this._listeners = [];
  }

  /** Register a callback invoked whenever a new note completes. */
  onNote(fn) {
    this._listeners.push(fn);
  }

  /**
   * Process one sketch frame.
   * @param {number[]|Float32Array} energies - 88 FFT energy values (0–255), one per piano key
   */
  pushFrame(energies) {
    for (let k = 0; k < 88; k++) {
      const e = energies[k] ?? 0;
      if (!this._active[k] && e > this._threshold) {
        // onset — note begins
        this._active[k] = { startFrame: this._frame };
      } else if (this._active[k] && e <= this._threshold) {
        // offset — note ends
        const dur = this._frame - this._active[k].startFrame;
        if (dur >= this._minDuration) {
          const note = {
            pitch: k + 20,  // pnoDist(88,12,440): key 49 = A4, so key 0 = MIDI 20
            start: this._active[k].startFrame,
            duration: dur,
          };
          this._notes.push(note);
          this._listeners.forEach(fn => fn(note));
        }
        this._active[k] = null;
      }
    }
    this._frame++;
  }

  /** Return all completed notes so far. */
  getNotes() {
    return this._notes;
  }

  /**
   * Return currently-active (in-progress) notes.
   * Use this to show notes in real time while they are still playing.
   * @returns {Array<{ pitch, start, duration }>}
   */
  getActive() {
    const active = [];
    for (let k = 0; k < 88; k++) {
      if (this._active[k]) {
        active.push({
          pitch: k + 20,
          start: this._active[k].startFrame,
          duration: this._frame - this._active[k].startFrame,
        });
      }
    }
    return active;
  }

  /** Reset state for a new recording session. */
  reset() {
    this._notes = [];
    this._active.fill(null);
    this._frame = 0;
  }
}
