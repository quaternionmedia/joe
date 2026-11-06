/**
 * PanelKeys — the windows by key: L the Library, A the analysis Results, and
 * Esc closes whichever of them and the Transcript are open. T, the
 * Transcript, is its own pane's key.
 *
 * R is not one of them: it asks the voice loop to say its question again
 * (VoiceKeys), and Shift+Esc stops listening. Keys are ignored while typing
 * in a field, and with a modifier held.
 *
 * Usage:
 *   new PanelKeys({ library: capturePanel, results: resultsPanel, transcript: transcriptPane }).mount();
 */
export class PanelKeys {
  /**
   * @param {object} panels
   * @param {{ isOpen: boolean, toggle(): void, close(): void }} panels.library
   * @param {{ isOpen: boolean, toggle(): void, close(): void }} panels.results
   * @param {{ isOpen: boolean, toggle(open?: boolean): void }} panels.transcript
   * @param {Document} [doc]
   */
  constructor({ library, results, transcript }, doc = document) {
    this._library    = library;
    this._results    = results;
    this._transcript = transcript;
    this._doc        = doc;
  }

  mount() {
    this._doc.addEventListener('keydown', e => this._key(e));
  }

  _key(e) {
    const t = e.target;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (e.repeat || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    if (e.code === 'KeyL') {
      e.preventDefault();
      this._library.toggle();
    } else if (e.code === 'KeyA') {
      e.preventDefault();
      this._results.toggle();
    } else if (e.code === 'Escape') {
      // Only what is open: a closed window is not opened to be closed.
      if (this._library.isOpen) this._library.close();
      if (this._results.isOpen) this._results.close();
      if (this._transcript.isOpen) this._transcript.toggle(false);
    }
  }
}
