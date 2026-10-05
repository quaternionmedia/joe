/**
 * TranscriptPane — the whole spoken exchange, readable in full, docked beside the piano roll.
 *
 * Every sentence the program asking said and every take joe heard, oldest first:
 * read from GET /api/voice/history when the page opens, so a reload keeps it,
 * and extended live from the conversation stream — the question as it is
 * asked, the take as it is written, a note when a take is marked or a level
 * shown. A take shows its words with the struck ones crossed out, how sure the
 * transcriber was, and how it was labelled. Nothing is cut short: the pane
 * scrolls, and follows the newest line unless it has been scrolled back.
 *
 * "What can be said" lists joe's own words (GET /api/voice/vocabulary) and the
 * conversation's (GET /v1/voice/vocabulary, the program asking), checks included.
 *
 * Open and close with `T`, the transport's Transcript button, or ×; the choice is
 * remembered in this browser. While open, the piano roll keeps its notes out from
 * under the pane.
 *
 * Usage:
 *   const pane = new TranscriptPane(document.getElementById('transcript-pane'), voicePanel, { canvas: mainCanvas });
 *   pane.mount();
 */
const OPEN_KEY = 'joe.transcript.open';
// How close to the bottom counts as following the newest line, in pixels.
const FOLLOW_PX = 48;

function remembered(storage) {
  try { return storage?.getItem(OPEN_KEY) === '1'; } catch { return false; }
}

function remember(storage, open) {
  try { storage?.setItem(OPEN_KEY, open ? '1' : '0'); } catch { /* a private window keeps nothing */ }
}

export class TranscriptPane {
  /**
   * @param {HTMLElement} el      - #transcript-pane
   * @param {object} panel        - the VoicePanel whose events carry the exchange
   * @param {object} [opts]
   * @param {object} [opts.canvas]  - the MainCanvas, told how much of it the pane covers
   * @param {string} [opts.base]    - joe's voice routes
   * @param {string} [opts.asking]  - the program asking's voice routes
   * @param {Document} [opts.doc]
   * @param {Storage} [opts.storage]
   */
  constructor(el, panel, { canvas = null, base = '/api/voice', asking = '/v1/voice',
                           doc = document, storage = globalThis.localStorage } = {}) {
    this._el      = el;
    this._panel   = panel;
    this._canvas  = canvas;
    this._base    = base;
    this._asking  = asking;
    this._doc     = doc;
    this._storage = storage;
    this._list    = el.querySelector('[data-testid="transcript-entries"]');
    this._say     = el.querySelector('[data-testid="transcript-say"]');
    this._empty   = el.querySelector('[data-testid="transcript-empty"]');
    this._entries = [];   // from the history, then live
    this._notes   = [];   // joe's notes, kept beside a refetched history
    this._onKey   = e => this._key(e);
    // Set by whatever shows a take elsewhere: called with the take's entry.
    this.onShow = null;
  }

  async mount() {
    this._doc.addEventListener('keydown', this._onKey);
    this._el.querySelector('[data-testid="transcript-close"]')
      ?.addEventListener('click', () => this.toggle(false));
    this._el.querySelector('[data-testid="transcript-say-toggle"]')
      ?.addEventListener('click', () => this._toggleSay());
    const previous = this._panel.onEvent;
    this._panel.onEvent = event => {
      if (previous) previous(event);
      this._event(event);
    };
    this.toggle(remembered(this._storage));
    await this.refresh();
  }

  get isOpen() { return !this._el.hidden; }

  toggle(open = !this.isOpen) {
    this._el.hidden = !open;
    this._doc.body.classList.toggle('transcript-open', open);
    remember(this._storage, open);
    this._canvas?.setInset?.(open ? this._el.offsetWidth : 0);
    if (open) this._follow(true);
  }

  /** Read the whole transcript again from joe. */
  async refresh() {
    try {
      const res = await fetch(`${this._base}/history?limit=500`);
      if (!res.ok) return;
      const body = await res.json();
      this._entries = body.entries || [];
      this._kept = body.kept !== false;
      this.render();
    } catch { /* no engine is a normal way to run the front end */ }
  }

  render() {
    const follow = this._following();
    const all = [...this._entries, ...this._notes].sort((a, b) => (a.at || 0) - (b.at || 0));
    this._list.replaceChildren(...all.map(entry => this._line(entry)));
    if (this._empty) {
      this._empty.hidden = all.length > 0;
      this._empty.textContent = this._kept === false
        ? 'joe keeps no transcript while JOE_DATAPOINTS=0; this one starts now.'
        : 'Nothing said yet. What is asked and what is heard appears here.';
    }
    this._follow(follow);
  }

  // ─── the exchange, live ───────────────────────────────────────────────────

  _event(event) {
    const at = event.at || Date.now() / 1000;
    if (event.state === 'speaking' && event.text) {
      this._entries.push({ kind: 'said', text: event.text, reason: event.reason, at });
    } else if (event.state === 'transcript' && event.take) {
      let take = this._entries.find(e => e.kind === 'take' && e.take === event.take);
      if (!take) {
        take = { kind: 'take', take: event.take, at, live: true, segments: [] };
        this._entries.push(take);
      }
      take.segments = event.segments || [];
      take.text = event.text;
    } else if (event.state === 'note' && event.text) {
      this._notes.push({ kind: 'note', text: event.text, at });
    } else if (['heard', 'no_speech', 'recorded', 'gave_up'].includes(event.state)) {
      // The take is over: what joe kept of it -- its confidence, its label -- is in the history.
      this.refresh();
      return;
    } else {
      return;
    }
    this.render();
  }

  // ─── one line ─────────────────────────────────────────────────────────────

  _line(entry) {
    const li = this._doc.createElement('li');
    li.className = `tp-entry tp-${entry.kind}`;
    const meta = this._doc.createElement('div');
    meta.className = 'tp-meta';
    meta.append(this._span('tp-who', { said: 'Asked', take: 'Heard', note: 'joe' }[entry.kind] || ''));
    if (entry.at) meta.append(this._span('tp-at', this._time(entry.at)));
    if (entry.kind === 'take') {
      li.dataset.take = entry.take;
      li.classList.toggle('is-live', !!entry.live);
      if (entry.source === 'key') meta.append(this._span('tp-tag', 'by key'));
      if (entry.over_question) meta.append(this._span('tp-tag', 'over the question'));
      if (typeof entry.confidence === 'number') {
        meta.append(this._span('tp-conf', `sure ${Math.round(entry.confidence * 100)}%`));
      }
      if (entry.label) {
        li.classList.add(`is-${entry.label.replace(' ', '-')}`);
        meta.append(this._span('tp-label', entry.label));
      }
      if (entry.outcome) meta.append(this._span('tp-tag', entry.outcome.replace('_', ' ')));
      if (this.onShow && entry.audio && entry.segments?.length) {
        const show = this._doc.createElement('button');
        show.type = 'button';
        show.className = 'tp-show';
        show.dataset.testid = 'transcript-show';
        show.textContent = 'Show';
        show.title = 'Play it on the piano roll, its words on the timeline';
        show.addEventListener('click', () => this.onShow(entry));
        meta.append(show);
      }
    }
    li.append(meta, this._body(entry));
    return li;
  }

  _body(entry) {
    const p = this._doc.createElement('p');
    p.className = 'tp-text';
    if (entry.kind !== 'take' || !entry.segments?.length) {
      p.textContent = entry.text || (entry.kind === 'take' ? '(nothing heard)' : '');
      return p;
    }
    entry.segments.forEach(segment => {
      if (segment.pending) {
        p.append(this._span('tp-word is-pending', '…'));
        return;
      }
      (segment.words || []).forEach((word, i) => {
        const span = this._span('tp-word', word);
        if ((segment.struck || []).includes(i)) span.classList.add('is-struck');
        p.append(span, ' ');
      });
    });
    return p;
  }

  _span(className, text) {
    const span = this._doc.createElement('span');
    span.className = className;
    span.textContent = text;
    return span;
  }

  _time(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  // ─── following the newest line ────────────────────────────────────────────

  _following() {
    const list = this._list;
    return list.scrollTop + list.clientHeight >= list.scrollHeight - FOLLOW_PX;
  }

  _follow(follow) {
    if (follow) this._list.scrollTop = this._list.scrollHeight;
  }

  // ─── what can be said ─────────────────────────────────────────────────────

  async _toggleSay() {
    this._say.hidden = !this._say.hidden;
    if (!this._say.hidden && !this._say.dataset.loaded) await this._loadSay();
  }

  async _loadSay() {
    const read = async url => {
      try { const res = await fetch(url); return res.ok ? await res.json() : null; } catch { return null; }
    };
    const [own, asking] = await Promise.all([read(`${this._base}/vocabulary`), read(`${this._asking}/vocabulary`)]);
    const sections = [];
    if (asking) {
      sections.push(this._group('To the conversation', asking.phrases || []));
      const checks = Object.entries(asking.projects || {}).flatMap(([project, p]) =>
        (p.checks || []).map(c => ({ key: `${project} · ${c.name}`, says: `${c.says} — runs ${c.command}`,
                                     phrases: c.phrases })));
      if (checks.length) sections.push(this._group('Checks, run after approve', checks));
    } else {
      sections.push(this._note('The conversation\'s words appear here while it is running.'));
    }
    if (own) sections.push(this._group('To joe, inside a take', own.phrases || []));
    this._say.replaceChildren(...sections);
    this._say.dataset.loaded = '1';
  }

  _group(title, items) {
    const section = this._doc.createElement('section');
    section.className = 'tp-say-group';
    const h = this._doc.createElement('h3');
    h.textContent = title;
    const dl = this._doc.createElement('dl');
    items.forEach(item => {
      const dt = this._doc.createElement('dt');
      dt.textContent = [...(item.phrases || []), ...(item.words || [])].map(p => `“${p}”`).join(' · ');
      const dd = this._doc.createElement('dd');
      dd.textContent = item.says;
      dl.append(dt, dd);
    });
    section.append(h, dl);
    return section;
  }

  _note(text) {
    const p = this._doc.createElement('p');
    p.className = 'tp-say-note';
    p.textContent = text;
    return p;
  }

  // ─── the key ──────────────────────────────────────────────────────────────

  _key(e) {
    const t = e.target;
    if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (e.code !== 'KeyT' || e.repeat || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    this.toggle();
  }
}
