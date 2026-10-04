/**
 * VoiceInstruct — "Instruct by voice": one spoken instruction into qmcp's inbox.
 *
 * The button asks qmcp to take an instruction aloud on this machine. qmcp runs
 * the dialog ("What should be done?", read back, recorded on a yes) and joe's
 * microphone hears it, so the voice panel shows the whole turn. When the
 * conversation ends, the newest row in the inbox is shown beside the queue:
 * the words, the project they resolved to or "no project", and whether the
 * row is recorded or unresolved. Nothing is spoken until the button is pressed.
 *
 * The button sits in the bottom bar rather than in the panel: the panel steps
 * aside when nothing is happening, and an instruction is given when nothing
 * is. The panel is where the outcome goes.
 *
 * A qmcp without the inbox answers 404 to the request, and the page says so
 * rather than failing: the queue above keeps working against that qmcp.
 *
 * Usage:
 *   const instruct = new VoiceInstruct(button, panelEl.querySelector('.voice-instruct'), voicePanel);
 *   instruct.mount();
 */
const FOLLOW_MS = 1000;
// An outcome stays on screen this long before the panel may step aside.
const LINGER_MS = 10000;

export class VoiceInstruct {
  /**
   * @param {HTMLElement} button - the "Instruct by voice" button, in the bottom bar
   * @param {HTMLElement} el     - .voice-instruct inside #voice-panel
   * @param {object} panel       - the VoicePanel, kept open while the outcome shows
   * @param {object} [opts]
   * @param {string} [opts.base] - where qmcp's API is reached
   */
  constructor(button, el, panel, { base = '/v1' } = {}) {
    this._button  = button;
    this._el      = el;
    this._panel   = panel;
    this._base    = base;
    this._note    = el.querySelector('[data-testid="voice-instruct-note"]');
    this._latest  = el.querySelector('[data-testid="voice-instruct-latest"]');
    this._text    = el.querySelector('[data-testid="voice-instruct-text"]');
    this._project = el.querySelector('[data-testid="voice-instruct-project"]');
    this._status  = el.querySelector('[data-testid="voice-instruct-status"]');
    this.running  = false;
    this._holding = false;
    this._timer   = null;
  }

  mount() {
    // Chained, not replaced: the queue holds the panel open for its own reasons.
    const prior = this._panel.keepOpen;
    this._panel.keepOpen = () => prior() || this.running || this._holding;
    this._button.addEventListener('click', () => this.instruct());
  }

  destroy() {
    clearTimeout(this._timer);
  }

  /** Have qmcp take one instruction aloud, follow it to its end, and show what was recorded. */
  async instruct() {
    if (this.running) return;
    this.running = true;
    this._button.disabled = true;
    this._latest.hidden = true;
    this._note.textContent = 'Asking aloud…';
    this._el.hidden = false;
    this._panel.reveal();

    try {
      const res = await fetch(`${this._base}/instructions/voice`, { method: 'POST' });
      if (res.status === 404) {
        this._note.textContent = 'This qmcp has no instruction inbox: it answered 404. The queue above still works.';
        return;
      }
      if (res.status !== 202) {
        const body = await res.json().catch(() => ({}));
        this._note.textContent = body.detail || `qmcp answered ${res.status}`;
        return;
      }
      const status = await this._follow();
      if (status.exit_code !== 0) {
        this._note.textContent =
          (status.output || []).at(-1) || `The conversation ended with code ${status.exit_code}`;
        return;
      }
      this._note.textContent = '';
      await this._showLatest();
    } catch (err) {
      this._note.textContent = `qmcp could not be reached: ${err.message}`;
    } finally {
      this.running = false;
      this._button.disabled = false;
      this._linger();
    }
  }

  async _follow() {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, FOLLOW_MS));
      const res = await fetch(`${this._base}/instructions/voice`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`qmcp answered ${res.status}`);
      const status = await res.json();
      if (!status.running) return status;
    }
  }

  /** The newest row in the inbox: the one the conversation that just ended recorded. */
  async _showLatest() {
    const res = await fetch(`${this._base}/instructions?limit=1`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`qmcp answered ${res.status}`);
    const { instructions = [] } = await res.json();
    const row = instructions[0];
    if (!row) {
      this._note.textContent = 'The conversation ended, and the inbox is empty.';
      return;
    }
    this._text.textContent = `“${row.text}”`;
    this._project.textContent = row.project || 'no project';
    this._status.textContent = row.status;
    this._latest.hidden = false;
  }

  _linger() {
    this._holding = true;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._holding = false;
      this._el.hidden = true;
      this._panel.settle();
    }, LINGER_MS);
  }
}
