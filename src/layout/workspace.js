import { GoldenLayout, LayoutConfig } from 'golden-layout';
import { WindowRegistry } from './registry.js';
import { DEFAULT_LAYOUT, REOPEN, SIDE_SIZE, windowConfig } from './default_layout.js';
import { forgetLayout, keepLayout, readSavedLayout, savedLayoutText } from './saved_layout.js';

/**
 * joe's dock: the visualiser and every panel as windows of one GoldenLayout,
 * built in the element the page gives it. What the rest of the page asks of it:
 *
 *   showWindow(id)   bring a window to the front of its stack -- reopening it,
 *                    in its place, if it was closed; never a second copy
 *   closeWindow(id)  close a window that can be closed
 *   toggle(id)       close a window in front, else bring it to the front
 *   isOpen(id)       whether a window is in the layout
 *   inFront(id)      whether it is the one its stack shows
 *   resetLayout()    the default arrangement, and forget the saved one
 *   window(id)       all of that for one window, for the panel it holds
 *
 * A window holds a panel the page built once: its element is moved into the
 * window, and moved to `parked` -- hidden, still in the page -- when the
 * window closes or the layout is rebuilt, so no panel starts over. The element
 * hears `joe:window` with `{ id, shown }` as it is shown or parked.
 *
 * A window is shown with `Stack.setActiveComponentItem`: `ComponentItem.focus()`
 * marks an item focused and leaves its stack showing whichever tab it showed.
 */
export class Workspace {
  /**
   * @param {HTMLElement} element  where the dock is built
   * @param {object} opts
   * @param {HTMLElement} opts.parked  where a closed window's element waits
   * @param {HTMLElement} [opts.note]  where the page says why a saved layout was dropped
   */
  constructor(element, { parked, note = null }) {
    this._host = element;
    this._parked = parked;
    this._note = note;
    this._noteTimer = null;
    this._gl = null;
    this._saveTimer = null;
    this._decorating = false;
    // Each window's element, found once: a window binds its panel from here,
    // wherever the panel was left.
    this._elements = new Map(WindowRegistry.all().map(w => [w.id, document.getElementById(w.element)]));
  }

  create() {
    const gl = new GoldenLayout(this._host);
    this._gl = gl;
    // Follow the element's size at once. GoldenLayout waits 100ms after the
    // last resize by default, and longer while resizes keep coming: for that
    // long every window is where it was.
    gl.resizeWithContainerAutomatically = true;
    gl.resizeDebounceInterval = 0;
    gl.resizeDebounceExtendedWhenPossible = false;
    for (const w of WindowRegistry.all()) {
      gl.registerComponentFactoryFunction(w.id, container => this._bind(w, container));
    }
    gl.on('stateChanged', () => {
      this._scheduleSave();
      this._queueDecorate();
    });
    gl.on('activeContentItemChanged', () => this._queueDecorate());
    this._host.addEventListener('keydown', e => this._onKeydown(e));
    // A change made just before the page goes -- a reload, the tab closed -- is
    // kept, rather than lost with the save still waiting.
    window.addEventListener('pagehide', () => { if (this._saveTimer) this._save(); });
    this._load();
    this._queueDecorate();
  }

  /** Bring window `id` to the front of its stack, reopening it if it was closed. */
  showWindow(id, { focus = true } = {}) {
    if (!this._gl || !WindowRegistry.get(id)) return;
    const item = this._find(id) || this._reopen(id);
    if (!item) return;
    const stack = item.parent;
    // A maximised stack hides the rest: a window elsewhere is not shown by
    // being brought to the front of a stack nobody can see.
    const maximised = this._gl.maximisedStack;
    if (maximised && maximised !== stack) maximised.minimise();
    if (stack?.isStack) stack.setActiveComponentItem(item, focus);
    this._queueDecorate();
  }

  /** Close window `id`, if it is open and can be closed. */
  closeWindow(id) {
    const item = this._find(id);
    if (item?.isClosable) item.close();
  }

  /** Close window `id` if it is in front; otherwise bring it to the front. */
  toggle(id) {
    if (this.inFront(id)) this.closeWindow(id);
    else this.showWindow(id);
  }

  /** Whether window `id` is in the layout. */
  isOpen(id) {
    return Boolean(this._find(id));
  }

  /** Whether window `id` is the one its stack shows, and no other stack is maximised over it. */
  inFront(id) {
    const item = this._find(id);
    if (!item) return false;
    const stack = item.parent;
    const maximised = this._gl.maximisedStack;
    if (maximised && maximised !== stack) return false;
    return !stack?.isStack || stack.getActiveComponentItem() === item;
  }

  /** Window `id`, for the panel it holds. */
  window(id) {
    const workspace = this;
    return {
      get isOpen() { return workspace.isOpen(id); },
      get inFront() { return workspace.inFront(id); },
      show: opts => workspace.showWindow(id, opts),
      close: () => workspace.closeWindow(id),
      toggle: () => workspace.toggle(id),
    };
  }

  /** The default arrangement, with the saved one forgotten. */
  resetLayout() {
    if (!this._gl) return;
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    forgetLayout();
    this._gl.loadLayout(DEFAULT_LAYOUT);
    this._queueDecorate();
  }

  _find(id) {
    return this._gl?.findFirstComponentItemById(id) ?? null;
  }

  /** Hold window `w`'s element in `container`, GoldenLayout's box for it. */
  _bind(w, container) {
    // The registry's title, whatever the layout it was loaded from says.
    container.setTitle(w.title);
    const element = this._elements.get(w.id);
    container.element.append(element);
    // Said on the next frame, once GoldenLayout has given the window its size:
    // what a panel does on being shown -- scroll to its end -- needs it.
    const shown = () => requestAnimationFrame(() => this._say(w.id, true));
    container.on('show', shown);
    container.on('beforeComponentRelease', () => this._park(w.id));
    shown();
    return undefined;
  }

  _park(id) {
    const element = this._elements.get(id);
    if (!element || element.parentElement === this._parked) return;
    this._parked.append(element);
    this._say(id, false);
  }

  _say(id, shown) {
    this._elements.get(id)?.dispatchEvent(new CustomEvent('joe:window', { detail: { id, shown } }));
  }

  /** The saved arrangement if it can be used, else the default. */
  _load() {
    const saved = readSavedLayout(savedLayoutText());
    if (saved.kind === 'unusable') this._drop(saved.why);
    const config = saved.kind === 'usable' ? saved.config : DEFAULT_LAYOUT;
    try {
      this._gl.loadLayout(config);
    } catch (err) {
      // It passed the check and GoldenLayout refused it anyway. The default
      // rather than a page with no windows; the default itself failing is a
      // bug, and throws.
      if (config === DEFAULT_LAYOUT) throw err;
      this._drop(`GoldenLayout refused it (${err?.message ?? err})`);
      this._gl.loadLayout(DEFAULT_LAYOUT);
    }
  }

  /** Forget the saved arrangement, and say why the default is showing. */
  _drop(why) {
    forgetLayout();
    if (!this._note) return;
    this._note.textContent = `Your arrangement of the windows could not be used, so the default is showing: ${why}.`;
    this._note.hidden = false;
    clearTimeout(this._noteTimer);
    this._noteTimer = setTimeout(() => { this._note.hidden = true; }, 8000);
  }

  _scheduleSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this._save(), 250);
  }

  _save() {
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    if (!this._gl?.isInitialised) return;
    try {
      keepLayout(LayoutConfig.fromResolved(this._gl.saveLayout()));
    } catch {
      // Caught mid-change; the next change saves it.
    }
  }

  /**
   * Put closed window `id` back: as a tab beside the windows it shares a
   * stack with, else in a stack of its own above the one it sits over, else in
   * a column of its own beside the visualiser.
   */
  _reopen(id) {
    const config = windowConfig(id);
    const rule = REOPEN[id] || { tabs: [], above: [] };
    for (const sibling of rule.tabs) {
      const item = this._find(sibling);
      if (item?.parent?.isStack) {
        item.parent.addItem(config);
        return this._find(id);
      }
    }
    for (const below of rule.above) {
      const stack = this._find(below)?.parent;
      if (!stack?.isStack) continue;
      if (stack.parent?.isColumn) {
        stack.parent.addItem({ type: 'stack', content: [config] }, stack.parent.contentItems.indexOf(stack));
        return this._find(id);
      }
      return this._rewrite(id, root => splitAbove(root, below, config));
    }
    const visualiser = this._find('visualiser')?.parent;
    const row = visualiser?.parent;
    if (row?.isRow) {
      const at = row.addItem({ type: 'stack', content: [config] }, row.contentItems.indexOf(visualiser) + 1);
      sizeAdded(row, row.contentItems[at], parseFloat(SIDE_SIZE));
      return this._find(id);
    }
    // The visualiser's stack is the whole dock: GoldenLayout folds a row away
    // when one item is left in it. A row again, on the layout as saved.
    return this._rewrite(id, root => ({
      type: 'row',
      content: [{ ...root, size: `${100 - parseFloat(SIDE_SIZE)}%` }, { type: 'stack', size: SIDE_SIZE, content: [config] }],
    }));
  }

  /** Load the layout as saved, its root changed by `change`, to open window `id`. */
  _rewrite(id, change) {
    const layout = LayoutConfig.fromResolved(this._gl.saveLayout());
    const root = change(layout.root);
    if (!root) return null;
    layout.root = root;
    this._gl.loadLayout(layout);
    return this._find(id);
  }

  /**
   * The keyboard on the dock: a tab is a tab, and the controls are buttons.
   * Enter or Space shows the focused tab's window; the arrow keys, Home and End
   * move along a stack's tabs; Delete closes a window that can be closed. Kept
   * from the page's own keys -- the arrows step the era panel -- which would
   * otherwise act on the same key.
   */
  _onKeydown(e) {
    const tab = e.target.closest?.('.lm_tab[data-window]');
    if (tab) {
      const id = tab.dataset.window;
      const tabs = [...tab.parentElement.querySelectorAll('.lm_tab[data-window]')];
      const at = tabs.indexOf(tab);
      const move = {
        ArrowRight: tabs[(at + 1) % tabs.length],
        ArrowDown: tabs[(at + 1) % tabs.length],
        ArrowLeft: tabs[(at - 1 + tabs.length) % tabs.length],
        ArrowUp: tabs[(at - 1 + tabs.length) % tabs.length],
        Home: tabs[0],
        End: tabs[tabs.length - 1],
      }[e.key];
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        this.showWindow(id);
        // GoldenLayout puts a stack's tabs back in their strip when one is
        // chosen, and an element put back loses the focus.
        tab.focus();
      } else if (move) {
        e.preventDefault();
        e.stopPropagation();
        move.focus();
      } else if (e.key === 'Delete') {
        e.preventDefault();
        e.stopPropagation();
        this.closeWindow(id);
      }
      return;
    }
    const control = e.target.closest?.('.lm_controls > [role="button"]');
    if (control && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      e.stopPropagation();
      control.click();
    }
  }

  _queueDecorate() {
    if (this._decorating) return;
    this._decorating = true;
    Promise.resolve().then(() => this._decorate());
  }

  /** Roles, names and tab stops for what GoldenLayout draws, which has none. */
  _decorate() {
    this._decorating = false;
    if (!this._gl?.rootItem) return;
    const visit = item => {
      if (!item) return;
      if (item.isComponent) decorateWindow(item);
      for (const child of item.contentItems) visit(child);
    };
    visit(this._gl.rootItem);
    for (const control of this._host.querySelectorAll('.lm_controls > *')) {
      control.setAttribute('role', 'button');
      control.tabIndex = 0;
    }
  }
}

/** Give `added`, just added to `row`, `percent` of it, the rest keeping their shares of what is left. */
function sizeAdded(row, added, percent) {
  const rest = row.contentItems.filter(item => item !== added);
  const total = rest.reduce((sum, item) => sum + item.size, 0) || 1;
  for (const item of rest) item.size = (item.size / total) * (100 - percent);
  added.size = percent;
  row.updateSize(false);
}

/**
 * In `root`, the stack holding window `anchor` replaced by a column of a new
 * stack of `entry` above it. Null when the anchor is not found.
 */
function splitAbove(root, anchor, entry) {
  const holds = item => item?.type === 'stack' && (item.content || []).some(c => c.componentType === anchor);
  let found = false;
  const visit = item => {
    if (!item || typeof item !== 'object') return item;
    if (holds(item)) {
      found = true;
      return {
        type: 'column',
        size: item.size,
        content: [{ type: 'stack', size: '40%', content: [entry] }, { ...item, size: '60%' }],
      };
    }
    return item.content ? { ...item, content: item.content.map(visit) } : item;
  };
  const changed = visit(root);
  return found ? changed : null;
}

function decorateWindow(item) {
  const w = WindowRegistry.get(item.id);
  if (!w) return;
  const stack = item.parent;
  const front = !stack?.isStack || stack.getActiveComponentItem() === item;
  const tab = item.tab?.element;
  if (tab) {
    tab.id = `paneltab-${w.id}`;
    tab.dataset.window = w.id;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-label', w.title);
    tab.setAttribute('aria-selected', front ? 'true' : 'false');
    tab.setAttribute('aria-controls', `panelbody-${w.id}`);
    if (item.isClosable) tab.setAttribute('aria-keyshortcuts', 'Delete');
    tab.tabIndex = front ? 0 : -1;
    if (tab.parentElement) {
      tab.parentElement.setAttribute('role', 'tablist');
      tab.parentElement.setAttribute('aria-label', 'Windows');
    }
    const close = tab.querySelector('.lm_close_tab');
    if (close) {
      // The ✕ is the mouse's way to close; the keyboard's is Delete on the tab.
      close.setAttribute('aria-hidden', 'true');
      close.title = `Close ${w.title}`;
    }
  }
  const body = item.container?.element;
  if (body) {
    body.id = `panelbody-${w.id}`;
    body.setAttribute('role', 'tabpanel');
    body.setAttribute('aria-labelledby', `paneltab-${w.id}`);
  }
}
