/**
 * Every window joe's page has, once.
 *
 * The one list of what a window is called and what it holds, in the manner of
 * codecartographer's and alfred's panel registries: the workspace registers
 * each with GoldenLayout under its id, the default layout places them by id,
 * and a saved layout is checked against these ids. A new window is an entry
 * here.
 *
 * `id` is also the window's GoldenLayout component type and its item id, so a
 * window is found -- to show it, or to know it is open rather than open a
 * second -- by `findFirstComponentItemById(id)`.
 *
 * `element` is the id of the page element the window holds: the panel itself,
 * built once as the page loads. A window moves its element, and a closed
 * window's element waits, hidden, in `#parked`, so nothing a panel holds
 * starts over when its window closes or the layout is rebuilt.
 *
 * `closable: false` keeps a window in the layout: the visualiser is what joe
 * is for, and every layout has it.
 *
 * @typedef {object} WindowDefinition
 * @property {string} id
 * @property {string} title
 * @property {string} element
 * @property {boolean} [closable]
 */

/** @type {readonly WindowDefinition[]} */
const WINDOWS = Object.freeze([
  { id: 'visualiser', title: 'Visualiser', element: 'visualiser', closable: false },
  { id: 'library', title: 'Library', element: 'capture-panel' },
  { id: 'results', title: 'Results', element: 'results-panel' },
  { id: 'transcript', title: 'Transcript', element: 'transcript-pane' },
  { id: 'voice', title: 'Voice', element: 'voice-panel' },
]);

export const WindowRegistry = {
  /** @returns {readonly WindowDefinition[]} */
  all: () => WINDOWS,
  /** @returns {WindowDefinition | undefined} */
  get: id => WINDOWS.find(w => w.id === id),
  /** @returns {string[]} */
  ids: () => WINDOWS.map(w => w.id),
};
