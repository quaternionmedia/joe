/**
 * VoiceTranscript — the take as it is written, with earlier words strikable.
 *
 * joe transcribes a take segment by segment while it is recorded and publishes
 * each step as a `transcript` event: `{ take, segments: [{ index, words, struck,
 * pending }], text }`. This shows the words as they arrive. Clicking a word
 * strikes it, or restores it; Backspace strikes the last word still standing
 * (POST /api/voice/strike). The take's text leaves struck words out, so what is
 * read back is what is shown here.
 *
 * Usage:
 *   const transcript = new VoiceTranscript(document.querySelector('#voice-panel .voice-transcript'), voicePanel);
 *   transcript.mount();
 */
export class VoiceTranscript {
  /**
   * @param {HTMLElement} el     - #voice-panel .voice-transcript
   * @param {object} panel       - the VoicePanel whose events carry the transcript
   * @param {object} [opts]
   * @param {string} [opts.base] - joe's voice routes
   * @param {Document} [opts.doc]
   */
  constructor(el, panel, { base = '/api/voice', doc = document } = {}) {
    this._el    = el;
    this._panel = panel;
    this._base  = base;
    this._doc   = doc;
    this._take  = null;
    this._onKey = e => this._key(e);
  }

  mount() {
    this._doc.addEventListener('keydown', this._onKey);
    const previous = this._panel.onEvent;
    this._panel.onEvent = event => {
      if (previous) previous(event);
      if (event.state === 'transcript') this.render(event);
    };
  }

  destroy() {
    this._doc.removeEventListener('keydown', this._onKey);
  }

  render({ take, segments = [] }) {
    this._take = take;
    const lines = segments.map(segment => {
      const line = this._doc.createElement('span');
      line.className = 'voice-segment';
      line.dataset.segment = segment.index;
      if (segment.pending) {
        line.classList.add('is-pending');
        line.textContent = '…';
        return line;
      }
      segment.words.forEach((word, i) => {
        const span = this._doc.createElement('button');
        span.type = 'button';
        span.className = 'voice-word';
        span.dataset.word = i;
        span.textContent = word;
        if (segment.struck.includes(i)) span.classList.add('is-struck');
        span.addEventListener('click', () => this.strike({ segment: segment.index, word: i }));
        line.append(span);
      });
      return line;
    });
    this._el.replaceChildren(...lines);
    this._el.hidden = segments.length === 0;
  }

  async strike(which) {
    if (!this._take) return;
    try {
      await fetch(`${this._base}/strike`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ take: this._take, ...which }),
      });
    } catch { /* no engine is a normal way to run the front end */ }
  }

  _key(e) {
    const t = e.target;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (e.code !== 'Backspace' || e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
    if (!this._take || this._el.hidden) return;
    e.preventDefault();
    this.strike({ last: true });
  }
}
