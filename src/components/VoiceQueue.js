/**
 * VoiceQueue — what is waiting on a person in qmcp, and "Answer by voice".
 *
 * Reads qmcp's human queue through the dev server's `/v1` proxy, oldest
 * first, and offers the oldest request. The button asks qmcp to put that
 * request to the person aloud; qmcp runs the dialog and joe's microphone
 * hears the answer, so the voice panel above shows the whole turn. Nothing is
 * spoken until the person presses the button.
 *
 * Usage:
 *   const queue = new VoiceQueue(panelEl.querySelector('.voice-queue'), voicePanel);
 *   queue.mount();   // polls the queue, backing off while qmcp is not running
 */
const POLL_MS = 5000;
const FOLLOW_MS = 1000;

export class VoiceQueue {
  /**
   * @param {HTMLElement} el     - .voice-queue inside #voice-panel
   * @param {object} panel       - the VoicePanel, kept open while anything waits
   * @param {object} [opts]
   * @param {string} [opts.base] - where qmcp's API is reached
   */
  constructor(el, panel, { base = '/v1' } = {}) {
    this._el      = el;
    this._panel   = panel;
    this._base    = base;
    this._count   = el.querySelector('[data-testid="voice-queue-count"]');
    this._prompt  = el.querySelector('[data-testid="voice-queue-prompt"]');
    this._note    = el.querySelector('[data-testid="voice-queue-note"]');
    this._button  = el.querySelector('[data-testid="voice-answer"]');
    this.pending  = [];
    this.running  = false;
    this._retryMs = POLL_MS;
    this._timer   = null;
  }

  mount() {
    // Chained, not replaced: whatever else lives in the panel holds it open too.
    const prior = this._panel.keepOpen;
    this._panel.keepOpen = () => prior() || this.pending.length > 0 || this.running;
    this._button.addEventListener('click', () => this.answer());
    this._poll();
  }

  destroy() {
    clearTimeout(this._timer);
  }

  /** Read the queue once. Throws when qmcp cannot be reached. */
  async refresh() {
    const res = await fetch(
      `${this._base}/human/requests?status=pending&oldest_first=true&limit=20`,
      { cache: 'no-store' });
    if (!res.ok) throw new Error(`qmcp answered ${res.status}`);
    const { requests = [] } = await res.json();
    this._render(requests);
  }

  /** Put the oldest waiting request to the person aloud, and follow it to its end. */
  async answer() {
    const first = this.pending[0];
    if (!first || this.running) return;
    this.running = true;
    this._button.disabled = true;
    this._note.textContent = 'Asking aloud…';

    try {
      const res = await fetch(
        `${this._base}/human/requests/${encodeURIComponent(first.id)}/voice`,
        { method: 'POST' });
      if (res.status !== 202) {
        const body = await res.json().catch(() => ({}));
        this._note.textContent = body.detail || `qmcp answered ${res.status}`;
        return;
      }
      const status = await this._follow();
      this._note.textContent = status.exit_code === 0
        ? ''
        : (status.output || []).at(-1) || `The conversation ended with code ${status.exit_code}`;
    } catch (err) {
      this._note.textContent = `qmcp could not be reached: ${err.message}`;
    } finally {
      this.running = false;
      await this.refresh().catch(() => this._render(this.pending));
    }
  }

  async _follow() {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, FOLLOW_MS));
      const res = await fetch(`${this._base}/human/voice`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`qmcp answered ${res.status}`);
      const status = await res.json();
      if (!status.running) return status;
    }
  }

  _render(requests) {
    this.pending = requests;
    const first = requests[0];
    this._el.hidden = !first && !this._note.textContent;
    this._count.textContent = first
      ? `${requests.length} waiting on you`
      : '';
    this._prompt.textContent = first
      ? `${first.prompt}${first.options?.length ? `  (${first.options.join(' / ')})` : ''}`
      : '';
    this._button.hidden = !first;
    this._button.disabled = this.running || !first;
    if (first || this._note.textContent) this._panel.reveal();
    else this._panel.settle();
  }

  async _poll() {
    try {
      if (!this.running) await this.refresh();
      this._retryMs = POLL_MS;
    } catch {
      // qmcp not running is a normal way to run joe. Back off rather than ask
      // every few seconds for as long as the page is open.
      this._retryMs = Math.min(this._retryMs * 2, 60000);
    }
    this._timer = setTimeout(() => this._poll(), this._retryMs);
  }
}
