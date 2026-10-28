import { WindowRegistry } from './registry.js';
import { LAYOUT_SETTINGS } from './default_layout.js';

/**
 * The person's own arrangement of the dock: kept, checked, or dropped.
 *
 * Kept in this browser's localStorage, so it is per person and per browser,
 * and survives a reload. The key carries a version: a release whose windows
 * no longer fit an older arrangement moves to a new key rather than reading
 * one it cannot use. Every touch of storage is guarded -- a browser can refuse
 * it outright (a private window, a full quota, a policy) -- and the dock then
 * opens as it does the first time.
 *
 * A saved arrangement is read before GoldenLayout sees it. GoldenLayout throws
 * on a component type nobody registered, and the workspace loads the layout as
 * the page starts: a layout naming a window this version lacks would leave a
 * page with none. So it is read as plain JSON and loaded only if it is a
 * layout, every window in it is registered and appears once, under its
 * registry id, and the visualiser -- which cannot be closed -- is in it.
 * Anything else is dropped for the default, and the page says why.
 */

export const LAYOUT_KEY = 'joe.layout.v1';

const CONTAINERS = new Set(['row', 'column', 'stack']);

/**
 * Read saved text: nothing saved, a layout to load, or why not.
 *
 * @param {string | null | undefined} raw
 * @param {readonly import('./registry.js').WindowDefinition[]} [windows]
 * @returns {{kind: 'none'} | {kind: 'usable', config: object} | {kind: 'unusable', why: string}}
 */
export function readSavedLayout(raw, windows = WindowRegistry.all()) {
  if (raw === null || raw === undefined || raw === '') return { kind: 'none' };
  let config;
  try {
    config = JSON.parse(raw);
  } catch {
    return { kind: 'unusable', why: 'it is not JSON' };
  }
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    return { kind: 'unusable', why: 'it is not a layout' };
  }
  if (!config.root || typeof config.root !== 'object' || Array.isArray(config.root)) {
    return { kind: 'unusable', why: 'it has no windows in it' };
  }
  if (Array.isArray(config.openPopouts) && config.openPopouts.length) {
    return { kind: 'unusable', why: 'it has windows popped out of the page' };
  }

  const known = new Map(windows.map(w => [w.id, w]));
  const seen = [];
  const problem = check(config.root, known, seen);
  if (problem) return { kind: 'unusable', why: problem };

  const twice = seen.filter((id, i) => seen.indexOf(id) !== i);
  if (twice.length) return { kind: 'unusable', why: `it shows ${twice[0]} twice` };
  const missing = windows.find(w => w.closable === false && !seen.includes(w.id));
  if (missing) return { kind: 'unusable', why: `it has no ${missing.title}` };

  return {
    kind: 'usable',
    config: {
      // Today's settings over whatever was saved with it: they are the page's,
      // not the person's arrangement.
      ...LAYOUT_SETTINGS,
      root: config.root,
      openPopouts: [],
    },
  };
}

/** Why `item` cannot be loaded, or nothing; collects the window ids it names. */
function check(item, known, seen) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return 'it has an item that is not one';
  if (item.type === 'component') {
    const w = known.get(item.componentType);
    if (!w) return `it names ${JSON.stringify(item.componentType)}, which this version does not have`;
    if (item.id !== w.id) return `its ${w.title} window is not under its id`;
    // The registry's title and closability, not the saved ones.
    item.title = w.title;
    item.isClosable = w.closable !== false;
    seen.push(w.id);
    return null;
  }
  if (!CONTAINERS.has(item.type)) return `it has an item of a kind GoldenLayout does not know (${JSON.stringify(item.type)})`;
  if (!Array.isArray(item.content) || item.content.length === 0) return `it has an empty ${item.type}`;
  for (const child of item.content) {
    if (item.type === 'stack' && (!child || child.type !== 'component')) return 'it has a stack holding something other than windows';
    const problem = check(child, known, seen);
    if (problem) return problem;
  }
  return null;
}

/**
 * `config` without the windows in `ids`. A stack or a row left with nothing
 * goes too; a removed item's share of its row or column goes to the item
 * before it, else the one after; a stack shows the window it showed, or the
 * one beside it.
 *
 * @param {object} config  a layout as `LayoutConfig.fromResolved` gives it
 * @param {Iterable<string>} ids
 * @returns {object}
 */
export function withoutWindows(config, ids) {
  const leave = new Set(ids);
  if (!leave.size) return config;
  return { ...config, root: prune(config.root, leave) };
}

function prune(item, leave) {
  if (item.type === 'component') return leave.has(item.componentType) ? null : item;
  const left = item.content.map(child => prune(child, leave));
  const kept = left.filter(Boolean);
  if (!kept.length) return null;
  if (item.type === 'stack') {
    const active = item.activeItemIndex ?? 0;
    const before = left.slice(0, active).filter(Boolean).length;
    return { ...item, content: kept, activeItemIndex: Math.min(before, kept.length - 1) };
  }
  const content = left.map(child => child && { ...child });
  item.content.forEach((child, i) => {
    if (left[i] || !/%$/.test(child.size ?? '')) return;
    const to = content.slice(0, i).reverse().find(Boolean) ?? content.slice(i + 1).find(Boolean);
    if (/%$/.test(to.size ?? '')) to.size = `${parseFloat(to.size) + parseFloat(child.size)}%`;
  });
  return { ...item, content: content.filter(Boolean) };
}

/** The saved text, or null when there is none or storage is refused. */
export function savedLayoutText() {
  try {
    return window.localStorage.getItem(LAYOUT_KEY);
  } catch {
    return null;
  }
}

/** Keep `config` as this person's arrangement. False when storage refuses. */
export function keepLayout(config) {
  try {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(config));
    return true;
  } catch {
    return false;
  }
}

/** Forget the saved arrangement. */
export function forgetLayout() {
  try {
    window.localStorage.removeItem(LAYOUT_KEY);
  } catch {
    // Refused: there is nothing this page can do about it, and nothing lost.
  }
}
