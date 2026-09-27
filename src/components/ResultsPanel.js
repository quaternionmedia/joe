import { animate } from 'animejs';

/**
 * ResultsPanel — slide-in right panel for backend JSON output.
 *
 * Parsing and note rendering are delegated to MainCanvas.
 * This panel handles only metadata display and file/fetch controls.
 */
export class ResultsPanel {
  /**
   * @param {HTMLElement} el         - #results-panel container
   * @param {MainCanvas}  mainCanvas
   */
  constructor(el, mainCanvas) {
    this._el         = el;
    this._mainCanvas = mainCanvas;
    this._fileInput  = el.querySelector('[data-testid="file-input"]');
    this._errorEl    = el.querySelector('[data-testid="load-error"]');
    this._metaEl     = el.querySelector('[data-testid="results-meta"]');
    this._isOpen     = false;
    this._onFileChange = this._onFileChange.bind(this);
  }

  mount() {
    this._fileInput.addEventListener('change', this._onFileChange);
    const fetchBtn = this._el.querySelector('[data-testid="fetch-latest"]');
    if (fetchBtn) fetchBtn.addEventListener('click', () => this.fetchLatest());
  }

  toggle() { this._isOpen ? this.close() : this.open(); }

  /** Animation A — slide in */
  open() {
    this._isOpen = true;
    animate(this._el, { translateX: ['100%', '0%'], duration: 320, ease: 'outQuart' });
  }

  /** Animation B — slide out */
  close() {
    this._isOpen = false;
    animate(this._el, { translateX: ['0%', '100%'], duration: 280, ease: 'inQuart' });
  }

  async fetchLatest() {
    try {
      const res = await fetch('/api/results/latest', { cache: 'no-store' });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const data = await res.json();
      this._clearError();
      this.loadJSON(data);
    } catch (err) {
      this._showError();
      console.error('[ResultsPanel] fetchLatest failed:', err);
    }
  }

  /**
   * Parse a Process_Data JSON object and load note events into MainCanvas.
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
    this._mainCanvas.loadNotes(notes);
    document.dispatchEvent(new CustomEvent('joe:notesLoaded'));
  }

  // ─── Private ───────────────────────────────────────────────────────────────

  _onFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        this._clearError();
        this.loadJSON(JSON.parse(evt.target.result));
      } catch {
        this._showError();
      }
    };
    reader.readAsText(file);
    e.target.value = '';
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
    this._mainCanvas.clearNotes();
    document.dispatchEvent(new CustomEvent('joe:notesCleared'));
  }

  _clearError() {
    this._errorEl.hidden = true;
  }
}
