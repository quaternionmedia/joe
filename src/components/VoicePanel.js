/**
 * VoicePanel — a spoken exchange, live, from joe's conversation stream.
 *
 * The states are the polite conversation protocol (Modules/Conversation.py):
 * the question is asked with the microphone closed, the listener waits for the
 * person to begin, never interrupts while they speak, holds the turn open
 * through a pause, and only then reads what was said. Each state has its own
 * colour, motion, label and place on the track, so any one of them tells the
 * states apart.
 *
 * joe reports the microphone's states itself; the program asking the question
 * posts `speaking`, `recorded`, `gave_up` and `idle`.
 *
 * Usage:
 *   const panel = new VoicePanel(document.getElementById('voice-panel'));
 *   panel.mount();   // subscribes to /api/voice/conversation
 */
export const STATES = {
  speaking:     { label: 'Asking',           hint: 'Microphone closed while the question is spoken', step: 'speaking' },
  listening:    { label: 'Your turn',        hint: 'Microphone open. Speak when ready',              step: 'listening' },
  hearing:      { label: 'Hearing you',      hint: 'Not interrupting',                               step: 'hearing' },
  pausing:      { label: 'Pause',            hint: 'Holding the turn open in case there is more',    step: 'pausing' },
  transcribing: { label: 'Reading',          hint: 'Turn ended. Reading what was said',              step: 'transcribing' },
  heard:        { label: 'Heard',            hint: '',                                               step: 'outcome' },
  no_speech:    { label: 'Heard nothing',    hint: 'Nobody spoke before the turn ran out',           step: 'outcome' },
  recorded:     { label: 'Recorded',         hint: 'Answer accepted',                                step: 'outcome' },
  gave_up:      { label: 'Nothing recorded', hint: 'No usable answer. Nothing was guessed',          step: 'outcome' },
  idle:         { label: 'Idle',             hint: '',                                               step: null },
};

const REASKS = {
  noinput: 'Asking again: nothing was heard',
  nomatch: 'Asking again: that matched no option',
};

// A finished exchange stays on screen this long before the panel steps aside.
const LINGER_MS = 10000;
const FINISHED = ['recorded', 'gave_up', 'idle', 'no_speech'];
const LOG_LINES = 8;

export class VoicePanel {
  /**
   * @param {HTMLElement} el   - #voice-panel
   * @param {object} [opts]
   * @param {string} [opts.url] - the conversation stream
   */
  constructor(el, { url = '/api/voice/conversation' } = {}) {
    this._el      = el;
    this._url     = url;
    this._label   = el.querySelector('[data-testid="voice-label"]');
    this._hint    = el.querySelector('[data-testid="voice-hint"]');
    this._log     = el.querySelector('[data-testid="voice-log"]');
    this._fill    = el.querySelector('.voice-level-fill');
    this._gate    = el.querySelector('.voice-level-gate');
    this._steps   = [...el.querySelectorAll('[data-step]')];
    this._source  = null;
    this._retryMs = 2000;
    this._linger  = null;
    // Set by whatever else lives in the panel: while it returns true, a
    // finished exchange does not take the panel away.
    this.keepOpen = () => false;
  }

  /** Show the panel, whatever state it is in. */
  reveal() {
    this._el.hidden = false;
  }

  /** Step aside if nothing is happening and nothing needs the panel. */
  settle() {
    const finished = FINISHED.includes(this._el.dataset.state);
    if (finished && this._linger === null && !this.keepOpen()) this._el.hidden = true;
  }

  mount() {
    this._connect();
  }

  destroy() {
    if (this._source) this._source.close();
    clearTimeout(this._linger);
  }

  /** Apply one conversation event: `{ seq, state, text, reason? }`. */
  show(event) {
    const spec = STATES[event.state];
    if (!spec) return;

    this._el.hidden = false;
    this._el.dataset.state = event.state;
    this._label.textContent = spec.label;
    this._hint.textContent =
      (event.state === 'speaking' && REASKS[event.reason]) ||
      (event.state === 'idle' && event.text) ||
      spec.hint;

    const at = this._steps.findIndex(li => li.dataset.step === spec.step);
    this._steps.forEach((li, i) => {
      li.classList.toggle('is-current', i === at);
      li.classList.toggle('is-done', at >= 0 && i < at);
    });

    this._append(event);

    clearTimeout(this._linger);
    this._linger = null;
    if (FINISHED.includes(event.state)) {
      this._linger = setTimeout(() => {
        this._linger = null;
        if (!this.keepOpen()) this._el.hidden = true;
      }, LINGER_MS);
    }
  }

  /** The microphone's level: `{ rms, threshold }`. */
  level({ rms = 0, threshold = null } = {}) {
    // The gate sits at the middle of the bar, so speech reads as crossing it.
    const scale = threshold ? threshold * 2 : 0.05;
    this._fill.style.width = `${Math.min(100, (rms / scale) * 100)}%`;
    this._gate.hidden = !threshold;
  }

  _append(event) {
    const line = document.createElement('li');
    line.dataset.state = event.state;
    if (event.state === 'speaking') {
      line.className = 'voice-line voice-line-asked';
      line.textContent = event.text || STATES.speaking.label;
    } else if (event.state === 'heard') {
      line.className = 'voice-line voice-line-said';
      line.textContent = event.text ? `“${event.text}”` : '(nothing clear)';
    } else if (event.state === 'no_speech') {
      line.className = 'voice-line voice-line-said is-muted';
      line.textContent = '(silence)';
    } else if (event.state === 'recorded') {
      line.className = 'voice-line voice-line-outcome';
      line.textContent = `Recorded: ${event.text}`;
    } else if (event.state === 'gave_up') {
      line.className = 'voice-line voice-line-outcome is-refused';
      line.textContent = 'Nothing recorded';
    } else {
      return;
    }
    this._log.append(line);
    while (this._log.children.length > LOG_LINES) this._log.firstElementChild.remove();
  }

  _connect() {
    const source = new EventSource(this._url);
    this._source = source;

    source.onopen = () => {
      // The server replays its recent events on every connection, so the log
      // starts over rather than showing them twice.
      this._retryMs = 2000;
      this._log.replaceChildren();
    };
    source.onmessage = e => {
      try { this.show(JSON.parse(e.data)); } catch { /* one bad event is not the stream */ }
    };
    source.addEventListener('level', e => {
      try { this.level(JSON.parse(e.data)); } catch { /* as above */ }
    });
    source.onerror = () => {
      // No backend is a normal way to run the front end. Back off rather than
      // let the browser retry every few seconds for as long as the page is open.
      source.close();
      setTimeout(() => this._connect(), this._retryMs);
      this._retryMs = Math.min(this._retryMs * 2, 60000);
    };
  }
}
