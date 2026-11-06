/**
 * Capabilities — what this joe serves, read from /api/health, and what the
 * page says about one that is off.
 *
 * A fresh joe serves the media API alone; the microphone, the transcripts and
 * the audio library each wait for a JOE_ALLOW_ setting (docs/security.md).
 * Until the health route answers, or with no backend at all, nothing is known
 * and nothing is greyed: no backend is a normal way to run the front end.
 *
 * Usage:
 *   const caps = await new Capabilities().load();
 *   caps.off('library')            // ['library'] while it is off, else []
 *   markOff(button, caps.off('library'));
 *   list.append(offNote('library'));
 */

export const SECURITY_URL = 'https://github.com/quaternionmedia/joe/blob/main/docs/security.md';

// What turning each one on exposes, said where the page would have used it.
const OFF_TEXT = {
  microphone:  'The microphone is off. Turning it on lets anything that reaches this port record from this machine.',
  transcripts: 'The transcripts are off. Turning them on lets anything that reaches this port read every conversation joe has heard.',
  library:     'The library is off. Turning it on lets anything that reaches this port read and add recordings.',
};

/** The setting that turns `name` on: `JOE_ALLOW_LIBRARY` for `library`. */
export const setting = name => `JOE_ALLOW_${name.toUpperCase()}`;

export class Capabilities {
  /** @param {typeof fetch} [fetchImpl] */
  constructor(fetchImpl = (...args) => fetch(...args)) {
    this._fetch   = fetchImpl;
    this._allowed = null;   // { media, microphone, transcripts, library } once read
  }

  /** Read what is on. A joe that cannot be asked leaves everything unknown. */
  async load() {
    try {
      const res  = await this._fetch('/api/health', { cache: 'no-store' });
      const body = res.ok ? await res.json() : null;
      this._allowed = body?.allowed || null;
    } catch {
      this._allowed = null;
    }
    return this;
  }

  /** Whether joe said what is on; false before `load` or with no backend. */
  get known() { return this._allowed !== null; }

  /** Of `names`, those joe said are off; a name it did not mention is not. */
  off(...names) {
    return names.filter(name => this._allowed?.[name] === false);
  }
}

/** What a panel says in place of what it would show while `name` is off: a sentence and a link. */
export function offNote(name, doc = document) {
  const note = doc.createElement('span');
  note.className = 'off-note';
  note.dataset.testid = `off-${name}`;
  note.append(`${OFF_TEXT[name]} `);
  const link = doc.createElement('a');
  link.href = SECURITY_URL;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = 'docs/security.md';
  note.append(link);
  return note;
}

/** "a", "a and b", "a, b and c". */
const listed = items => items.length < 2 ? items.join('')
  : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;

/**
 * Keep the first-run hint's steps that work on this joe, numbered again, and
 * say in one line what `--allow` turns on for the rest. A step names what it
 * needs in `data-needs` and what it is in `data-what`.
 */
export function adaptHint(hintEl, caps, doc = document) {
  const steps = [...hintEl.querySelectorAll('.hint-step')];
  const needs = step => (step.dataset.needs || '').split(' ').filter(Boolean);
  const offSteps = steps.filter(step => caps.off(...needs(step)).length);
  if (!offSteps.length) return;

  const kept = steps.filter(step => !offSteps.includes(step));
  hintEl.querySelector('.hint-steps').replaceChildren(...kept.flatMap((step, i) => {
    step.querySelector('b').textContent = `${i + 1}.`;
    if (i === 0) return [step];
    const sep = doc.createElement('span');
    sep.className = 'hint-sep';
    sep.textContent = '·';
    return [sep, step];
  }));

  const names = [...new Set(offSteps.flatMap(step => caps.off(...needs(step))))];
  const line  = hintEl.querySelector('[data-testid="hint-off"]');
  const flags = names.map(name => {
    const code = doc.createElement('code');
    code.textContent = `--allow ${name}`;
    return code;
  });
  const link = doc.createElement('a');
  link.href = SECURITY_URL;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = 'docs/security.md';
  line.replaceChildren(...flags.flatMap((code, i) => i ? [' ', code] : [code]),
                       ` turns on ${listed(offSteps.map(step => step.dataset.what))} (`, link, ')');
  line.hidden = false;
}

/**
 * Grey `el` while any of `offNames` is off, its tooltip naming the setting;
 * restore its own tooltip once nothing is.
 */
export function markOff(el, offNames) {
  if (!('ownTitle' in el.dataset)) el.dataset.ownTitle = el.title || '';
  el.classList.toggle('is-off', offNames.length > 0);
  if (offNames.length) {
    el.dataset.off = offNames.join(' ');
    el.title = `Off on this joe: ${offNames.map(name => `${setting(name)}=1`).join(' and ')} turns it on`;
  } else {
    delete el.dataset.off;
    el.title = el.dataset.ownTitle;
  }
}
