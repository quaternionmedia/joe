import { WindowRegistry } from './registry.js';

/**
 * The dock as it first opens, and as Reset layout restores it: the visualiser
 * alone. Every other window opens beside it (REOPEN).
 *
 *   +--------------------------------------+
 *   | Visualiser                           |
 *   +--------------------------------------+
 *   first-run hint, transport: below the dock, not in it
 *
 * Every component entry carries `id`, equal to its registry id: a window is
 * found by `findFirstComponentItemById` -- to bring it forward, or to know it
 * is open rather than open a second -- and an entry without one is invisible
 * to that, as codecartographer found of its canvas.
 */

/** A component entry for registry window `id`, as every layout names it. */
export function windowConfig(id) {
  const w = WindowRegistry.get(id);
  if (!w) throw new Error(`no window is registered as ${id}`);
  return {
    type: 'component',
    componentType: w.id,
    id: w.id,
    title: w.title,
    isClosable: w.closable !== false,
  };
}

/** Settings every layout loads with, saved or default. */
export const LAYOUT_SETTINGS = Object.freeze({
  settings: {
    // The windows hold elements of this page: a popout window would open
    // empty. So there are none.
    popoutWholeStack: false,
    blockedPopoutsThrowError: false,
    closePopoutsOnUnload: true,
    constrainDragToContainer: true,
    reorderEnabled: true,
    responsiveMode: 'none',
  },
  header: {
    show: 'top',
    popout: false,
    maximise: 'Maximise',
    minimise: 'Restore',
    close: 'Close',
    tabDropdown: 'More windows',
  },
  dimensions: {
    borderWidth: 5,
    borderGrabWidth: 9,
    headerHeight: 28,
    // GoldenLayout 2.6.0 adds up the minimum of every tab in a stack when a
    // splitter beside it is dragged, though the tabs lie over one another:
    // four side windows at 160px would hold their stack 640px wide.
    defaultMinItemWidth: '60px',
    defaultMinItemHeight: '60px',
  },
});

export const DEFAULT_LAYOUT = Object.freeze({
  ...LAYOUT_SETTINGS,
  root: {
    type: 'row',
    content: [{ type: 'stack', content: [windowConfig('visualiser')] }],
  },
});

/** How wide a column of windows opens beside the visualiser. */
export const SIDE_SIZE = '32%';

/**
 * Where a closed window goes back to: as a tab beside the first of `tabs`
 * that is open, or else in a stack of its own above the first of `above`
 * that is open, or else in a column of its own beside the visualiser.
 *
 * The voice panel is a stack of its own, so a conversation does not cover the
 * transcript of it.
 */
export const REOPEN = Object.freeze({
  library: { tabs: ['results', 'transcript'], above: [] },
  results: { tabs: ['library', 'transcript'], above: [] },
  transcript: { tabs: ['library', 'results'], above: [] },
  voice: { tabs: [], above: ['transcript', 'library', 'results'] },
});
