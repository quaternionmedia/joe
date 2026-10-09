/**
 * VoiceKeys — answering the conversation without speaking, by key or button.
 *
 * A key or a button counts as having said the word: joe ends the take in
 * progress and hands the word to whoever asked (POST /api/voice/answer). So the
 * conversation runs the same whether an answer was spoken, pressed or clicked,
 * and a person who is not looking at the page needs only the keys:
 *
 *   1–9          the question's options, in the order it says them
 *   R            say that again
 *   Shift+Esc    stop listening
 *   ~ (held)     keep the turn open through pauses; releasing it ends the turn
 *
 * The options arrive with the question (`speaking` events carrying `options`)
 * and are shown as numbered buttons until the exchange moves on. Keys are
 * ignored while typing in a field.
 *
 * Usage:
 *   const keys = new VoiceKeys(document.querySelector('#voice-panel .voice-controls'), voicePanel);
 *   keys.mount();
 */
export const REPEAT = 'repeat';
export const STOP = 'stop listening';
// The states after which a question's options no longer apply.
const SETTLED = ['recorded', 'gave_up', 'idle'];

export class VoiceKeys {
  /**
   * @param {HTMLElement} el     - #voice-panel .voice-controls
   * @param {object} panel       - the VoicePanel whose events carry the options
   * @param {object} [opts]
   * @param {string} [opts.base] - joe's voice routes
   * @param {Document} [opts.doc]
   */
  constructor(el, panel, { base = '/api/voice', doc = document } = {}) {
    this._el      = el;
    this._panel   = panel;
    this._base    = base;
    this._doc     = doc;
    this._options = [];
    this._held    = false;
    this._list    = el.querySelector('[data-testid="voice-options"]');
    this._repeat  = el.querySelector('[data-testid="voice-repeat"]');
    this._stop    = el.querySelector('[data-testid="voice-stop"]');
    this._hold    = el.querySelector('[data-testid="voice-hold"]');
    this._onDown  = e => this._key(e, true);
    this._onUp    = e => this._key(e, false);
  }

  mount() {
    this._repeat.addEventListener('click', () => this.answer(REPEAT));
    this._stop.addEventListener('click', () => this.answer(STOP));
    this._doc.addEventListener('keydown', this._onDown);
    this._doc.addEventListener('keyup', this._onUp);
    // A window that loses focus mid-hold never sees the key come up.
    window.addEventListener('blur', () => this.hold(false));
    const previous = this._panel.onEvent;
    this._panel.onEvent = event => {
      if (previous) previous(event);
      this.follow(event);
    };
  }

  destroy() {
    this._doc.removeEventListener('keydown', this._onDown);
    this._doc.removeEventListener('keyup', this._onUp);
  }

  /** Keep the offered options in step with the exchange. */
  follow(event) {
    if (event.state === 'speaking') this.setOptions(event.options || []);
    else if (SETTLED.includes(event.state)) this.setOptions([]);
  }

  setOptions(options) {
    this._options = options.slice(0, 9);
    this._list.replaceChildren(...this._options.map((option, i) => {
      const button = this._doc.createElement('button');
      button.type = 'button';
      button.dataset.option = option;
      button.innerHTML = `<kbd>${i + 1}</kbd> `;
      button.append(option);
      button.addEventListener('click', () => this.answer(option));
      return button;
    }));
    this._list.hidden = this._options.length === 0;
  }

  async answer(text) {
    this._panel.reveal();
    try {
      await fetch(`${this._base}/answer`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text }),
      });
    } catch { /* no engine is a normal way to run the front end */ }
  }

  async hold(held) {
    if (held === this._held) return;
    this._held = held;
    this._hold.classList.toggle('is-held', held);
    try {
      await fetch(`${this._base}/hold`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ held }),
      });
    } catch { /* as above */ }
  }

  _key(e, down) {
    const t = e.target;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (e.code === 'Backquote') {
      e.preventDefault();
      if (down && e.repeat) return;
      this.hold(down);
      return;
    }
    if (!down || e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.code === 'Escape' && e.shiftKey) {
      e.preventDefault();
      this.answer(STOP);
      return;
    }
    if (e.shiftKey) return;
    const digit = /^(?:Digit|Numpad)([1-9])$/.exec(e.code);
    if (digit) {
      const option = this._options[Number(digit[1]) - 1];
      if (option) { e.preventDefault(); this.answer(option); }
      return;
    }
    if (e.code === 'KeyR') {
      e.preventDefault();
      this.answer(REPEAT);
    }
  }
}
