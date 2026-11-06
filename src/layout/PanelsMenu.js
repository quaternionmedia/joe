import { WindowRegistry } from './registry.js';

/**
 * The Panels menu: every window, and the default arrangement.
 *
 * Choosing a window shows it: brought to the front of its stack if it is in
 * the dock, put back in its place if it was closed -- never a second copy. A
 * closed one says so. Reset layout is the arrangement the dock first opened
 * with, and forgets the saved one.
 *
 * A menu button in the WAI-ARIA sense: Enter, Space or the arrow keys open it
 * with the focus on an item, the arrow keys, Home and End move between items,
 * Escape closes it and gives the focus back to the button, and so does a click
 * anywhere else. Keys pressed in the menu are the menu's: Escape there does not
 * also close the windows (PanelKeys).
 *
 * Usage:
 *   new PanelsMenu(button, list, workspace).mount();
 */
export class PanelsMenu {
  constructor(button, list, workspace) {
    this._button = button;
    this._list = list;
    this._workspace = workspace;
    this._teardown = null;
  }

  mount() {
    this._button.addEventListener('click', () => (this.isOpen ? this.close() : this.open('first')));
    this._button.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        this.open('first');
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        this.open('last');
      }
    });
    this._list.addEventListener('keydown', e => this._onKeydown(e));
  }

  get isOpen() { return !this._list.hidden; }

  open(focus) {
    this._draw();
    this._list.hidden = false;
    this._button.setAttribute('aria-expanded', 'true');
    const items = this._items();
    (focus === 'last' ? items[items.length - 1] : items[0])?.focus();
    // Armed after the click that opened it has finished, or that same click
    // would close it again.
    const outside = e => {
      if (!this._list.contains(e.target) && !this._button.contains(e.target)) this.close();
    };
    const timer = setTimeout(() => document.addEventListener('pointerdown', outside, true));
    this._teardown = () => {
      clearTimeout(timer);
      document.removeEventListener('pointerdown', outside, true);
    };
  }

  close({ refocus = false } = {}) {
    if (!this.isOpen) return;
    this._list.hidden = true;
    this._button.setAttribute('aria-expanded', 'false');
    this._teardown?.();
    this._teardown = null;
    if (refocus) this._button.focus();
  }

  _items() {
    return [...this._list.querySelectorAll('[role="menuitem"]')];
  }

  _draw() {
    const item = (label, attrs, onChoose) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'none');
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'menuitem');
      for (const [k, v] of Object.entries(attrs)) button.setAttribute(k, v);
      button.append(...label);
      button.addEventListener('click', onChoose);
      li.append(button);
      return li;
    };
    const span = (cls, text) => {
      const s = document.createElement('span');
      s.className = cls;
      s.textContent = text;
      return s;
    };
    const rows = WindowRegistry.all().map(w => {
      const closed = !this._workspace.isOpen(w.id);
      return item([span('pm-name', w.title), ...(closed ? [span('pm-state', 'closed')] : [])],
                  { 'data-panel': w.id, class: closed ? 'closed' : '' },
                  () => this._choose(w.id));
    });
    const divider = document.createElement('li');
    divider.setAttribute('role', 'separator');
    divider.className = 'pm-divider';
    const reset = item(['Reset layout'], { id: 'reset-layout' }, () => {
      this._workspace.resetLayout();
      this.close({ refocus: true });
    });
    this._list.replaceChildren(...rows, divider, reset);
  }

  // The focus goes where the choice took effect: the window's own tab, once it
  // has been drawn and named.
  _choose(id) {
    this._workspace.showWindow(id);
    this.close();
    setTimeout(() => document.getElementById(`paneltab-${id}`)?.focus());
  }

  _onKeydown(e) {
    const all = this._items();
    const at = all.indexOf(document.activeElement);
    const next = {
      ArrowDown: all[(at + 1) % all.length],
      ArrowUp: all[(at - 1 + all.length) % all.length],
      Home: all[0],
      End: all[all.length - 1],
    }[e.key];
    if (next) {
      e.preventDefault();
      next.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.close({ refocus: true });
    } else if (e.key === 'Tab') {
      this.close();
    }
    // Nothing in the menu is the page's to handle.
    e.stopPropagation();
  }
}
