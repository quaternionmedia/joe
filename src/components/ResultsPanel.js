import { animate } from 'animejs';
import { PianoRoll } from './PianoRoll.js';

/**
 * ResultsPanel — slide-in right panel for backend JSON output.
 *
 * anime.js animations used:
 *   A — panel slide-in  (translateX 100% → 0%)
 *   B — panel slide-out (translateX 0%  → 100%)
 *   E — piano roll canvas opacity 0 → 1 after render
 */
export class ResultsPanel {
  /** @param {HTMLElement} el - #results-panel container */
  constructor(el) {
    this._el        = el;
    this._fileInput = el.querySelector('[data-testid="file-input"]');
    this._errorEl   = el.querySelector('[data-testid="load-error"]');
    this._metaEl    = el.querySelector('[data-testid="results-meta"]');
    this._canvasEl  = el.querySelector('[data-testid="piano-roll-canvas"]');
    this._pianoRoll = new PianoRoll(this._canvasEl);
    this._isOpen    = false;
    this._onFileChange = this._onFileChange.bind(this);
  }

  mount() {
    this._fileInput.addEventListener('change', this._onFileChange);
    this._injectLegend();

    const fetchBtn = this._el.querySelector('[data-testid="fetch-latest"]');
    if (fetchBtn) fetchBtn.addEventListener('click', () => this.fetchLatest());
  }

  toggle() {
    this._isOpen ? this.close() : this.open();
  }

  /** Animation A — slide in */
  open() {
    this._isOpen = true;
    animate(this._el, {
      translateX: ['100%', '0%'],
      duration: 320,
      ease: 'outQuart',
    });
  }

  /** Animation B — slide out */
  close() {
    this._isOpen = false;
    animate(this._el, {
      translateX: ['0%', '100%'],
      duration: 280,
      ease: 'inQuart',
    });
  }

  /**
   * Fetch the most recent pipeline output from the API and render it.
   * Requires the FastAPI server to be running (`joe backend` or `joe dev`).
   */
  async fetchLatest() {
    try {
      const res = await fetch('/api/results/latest');
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`${res.status}: ${detail}`);
      }
      const data = await res.json();
      this._clearError();
      this.loadJSON(data);
    } catch (err) {
      this._showError();
      console.error('[ResultsPanel] fetchLatest failed:', err);
    }
  }

  // ─── Private ───────────────────────────────────────────────────────────────

  _onFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const data = JSON.parse(evt.target.result);
        this._clearError();
        this.loadJSON(data);
      } catch {
        this._showError();
      }
    };
    reader.readAsText(file);

    // Reset so the same file can be re-loaded
    e.target.value = '';
  }

  /**
   * Parse a Process_Data JSON object and render its note events.
   * @param {Object} data - parsed Process_Data JSON
   */
  loadJSON(data) {
    const notes = [];

    for (const trackName of Object.keys(data.audio || {})) {
      const track = data.audio[trackName];

      for (const transformType of Object.keys(track.chroma || {})) {
        const midiNotes = track.chroma[transformType]?.midi?.notes;
        if (!Array.isArray(midiNotes)) continue;

        for (const n of midiNotes) {
          for (const sd of n.start_dur || []) {
            notes.push({
              note:       n.note,
              pitch:      n.pitch,
              start_time: sd.start_time,
              duration:   sd.duration,
              type:       transformType,
              track:      trackName,
            });
          }
        }
      }
    }

    this._renderMeta(data, notes);
    this._pianoRoll.render(notes);

    // Animation E — fade in the canvas after render
    animate(this._canvasEl, {
      opacity: [0, 1],
      duration: 400,
      ease: 'outCubic',
    });
  }

  _renderMeta(data, notes) {
    const tracks = Object.keys(data.audio || {});
    const types  = [...new Set(notes.map(n => n.type))];
    this._metaEl.innerHTML = `
      <div>Iteration: ${data.iteration || '—'}</div>
      <div>Track${tracks.length !== 1 ? 's' : ''}: ${tracks.join(', ') || '—'}</div>
      <div>Notes: ${notes.length} events across ${types.join(', ')}</div>
    `;
  }

  _showError() {
    this._errorEl.hidden = false;
    this._metaEl.innerHTML = '';
    this._pianoRoll.clear();
  }

  _clearError() {
    this._errorEl.hidden = true;
  }

  _injectLegend() {
    const legend = document.createElement('div');
    legend.className = 'piano-roll-legend';
    legend.innerHTML = `
      <div class="legend-item">
        <div class="legend-swatch" style="background:#ffffff"></div> Raw
      </div>
      <div class="legend-item">
        <div class="legend-swatch" style="background:#00e5ff"></div> Harmonic
      </div>
      <div class="legend-item">
        <div class="legend-swatch" style="background:#ff6d00"></div> Percussive
      </div>
    `;
    this._canvasEl.insertAdjacentElement('beforebegin', legend);
  }
}
