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

// How far apart a sentence streamed and the same sentence kept may be stamped.
const SAME_SECONDS = 30;

// A question longer than this, in characters, is shown three lines deep until opened.
const LONG_ASK = 240;

/**
 * The history read from joe, with whatever streamed in that it does not hold
 * yet: a history that arrives after the stream has begun must not take the
 * newest lines away. A take is the same take by its id; a sentence is the same
 * sentence by its words, stamped within `SAME_SECONDS`.
 */
function merged(history, current) {
  const takes = new Set(history.filter(e => e.kind === 'take').map(e => e.take));
  const said = history.filter(e => e.kind === 'said');
  const newer = current.filter(e => e.streamed && (e.kind === 'take'
    ? !takes.has(e.take)
    : !said.some(s => s.text === e.text && Math.abs((s.at || 0) - (e.at || 0)) < SAME_SECONDS)));
  return [...history, ...newer];
}

/** A take that heard nothing: no words in any segment, no text, and no longer being written. */
function heardNothing(entry) {
  return entry.kind === 'take' && !entry.live && !(entry.text || '').trim()
    && !(entry.segments || []).some(segment => (segment.words || []).length);
}

/**
 * How the transcript names the day `date` falls on, seen from `now`: "Today",
 * "Yesterday", and before that the date, with its year when it is not this one.
 */
export function dayLabel(date, now) {
  const start = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((start(now) - start(date)) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  const parts = { weekday: 'short', day: 'numeric', month: 'short' };
  if (date.getFullYear() !== now.getFullYear()) parts.year = 'numeric';
  return date.toLocaleDateString([], parts);
}

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
    this._unfolded = new Set();   // runs of empty takes opened, by their first take
    this._unclamped = new Set();  // long questions opened, by when and what was said
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
      this._entries = merged(body.entries || [], this._entries);
      this._kept = body.kept !== false;
      this.render();
    } catch { /* no engine is a normal way to run the front end */ }
  }

  render() {
    const follow = this._following();
    const all = [...this._entries, ...this._notes].sort((a, b) => (a.at || 0) - (b.at || 0));
    this._list.replaceChildren(...this._lines(all));
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
    // A stream that reconnects sends what it sent before; joe stamps every
    // event, so one stamped no later than the last handled is a repeat. A
    // restarted joe stamps later, and is heard.
    if (event.at && this._lastAt && event.at <= this._lastAt) return;
    if (event.at) this._lastAt = event.at;
    const at = event.at || Date.now() / 1000;
    if (event.state === 'speaking' && event.text) {
      this._entries.push({ kind: 'said', text: event.text, reason: event.reason, at, streamed: true });
    } else if (event.state === 'transcript' && event.take) {
      let take = this._entries.find(e => e.kind === 'take' && e.take === event.take);
      if (!take) {
        take = { kind: 'take', take: event.take, at, live: true, streamed: true, segments: [] };
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

  // ─── the lines, and the takes that heard nothing ──────────────────────────

  /**
   * One line an entry, except that takes in a row that heard nothing share one,
   * folded; and a line naming the day wherever the day changes.
   */
  _lines(entries) {
    const lines = [];
    let day = null;
    const dayOf = at => {
      if (!at) return;
      const date = new Date(at * 1000);
      if (date.toDateString() === day) return;
      day = date.toDateString();
      lines.push(this._day(date));
    };
    for (let i = 0; i < entries.length;) {
      dayOf(entries[i].at);
      if (!heardNothing(entries[i])) {
        lines.push(this._line(entries[i++]));
        continue;
      }
      const run = [];
      while (i < entries.length && heardNothing(entries[i])) run.push(entries[i++]);
      lines.push(this._fold(run));
    }
    return lines;
  }

  _day(date) {
    const li = this._doc.createElement('li');
    li.className = 'tp-day';
    li.dataset.testid = 'transcript-day';
    li.textContent = dayLabel(date, new Date());
    return li;
  }

  _fold(run) {
    const key = run[0].take;
    const li = this._doc.createElement('li');
    li.className = 'tp-fold';
    const toggle = this._doc.createElement('button');
    toggle.type = 'button';
    toggle.className = 'tp-fold-toggle';
    toggle.dataset.testid = 'transcript-fold';
    toggle.textContent = `${run.length} ${run.length === 1 ? 'take' : 'takes'}, nothing heard`;
    const items = this._doc.createElement('ol');
    items.className = 'tp-fold-items';
    items.append(...run.map(entry => this._line(entry)));
    const show = open => {
      items.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
    };
    show(this._unfolded.has(key));
    toggle.addEventListener('click', () => {
      const open = !this._unfolded.has(key);
      if (open) this._unfolded.add(key);
      else this._unfolded.delete(key);
      show(open);
    });
    li.append(toggle, items);
    return li;
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
    const body = this._body(entry);
    li.append(meta, body);
    if (entry.kind === 'said' && (entry.text || '').length > LONG_ASK) li.append(this._clamp(entry, body));
    return li;
  }

  /** A long question, three lines deep, and the button that opens it whole. */
  _clamp(entry, body) {
    const key = `${entry.at}|${entry.text.slice(0, 40)}`;
    const more = this._doc.createElement('button');
    more.type = 'button';
    more.className = 'tp-more';
    more.dataset.testid = 'transcript-more';
    const show = open => {
      body.classList.toggle('is-clamped', !open);
      more.textContent = open ? 'less' : 'more';
      more.setAttribute('aria-expanded', String(open));
    };
    show(this._unclamped.has(key));
    more.addEventListener('click', () => {
      const open = !this._unclamped.has(key);
      if (open) this._unclamped.add(key);
      else this._unclamped.delete(key);
      show(open);
    });
    return more;
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
