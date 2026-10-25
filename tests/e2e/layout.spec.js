const { test, expect } = require('@playwright/test');

// joe's windows: the visualiser and every panel are windows of one GoldenLayout
// dock (src/layout/), the first-run hint and the transport below it. The
// arrangement is kept in this browser under joe.layout.v1.

const LAYOUT_KEY = 'joe.layout.v1';

const tab = (page, id) => page.locator(`#paneltab-${id}`);
const body = (page, id) => page.locator(`#panelbody-${id}`);
const roll = page => page.getByTestId('piano-roll-canvas');
const saved = page => page.evaluate(key => localStorage.getItem(key), LAYOUT_KEY);

// This browser's saved arrangement, before the page's first load only: a reload
// reads what the page saved itself.
async function seed(page, raw) {
  await page.addInitScript(([key, value]) => {
    if (sessionStorage.getItem('seeded')) return;
    sessionStorage.setItem('seeded', '1');
    localStorage.setItem(key, value);
  }, [LAYOUT_KEY, raw]);
}

async function open(page) {
  await page.goto('/');
  await expect(tab(page, 'visualiser')).toBeVisible();
}

// The stack a window's tab is in, as its place among the dock's stacks.
const stackOf = (page, id) => tab(page, id).evaluate(el =>
  [...document.querySelectorAll('.lm_stack')].indexOf(el.closest('.lm_stack')));

test('joe opens with the visualiser alone, the first-run hint and the transport below it', async ({ page }) => {
  await open(page);

  await expect(page.locator('.lm_tab')).toHaveCount(1);
  await expect(tab(page, 'visualiser')).toHaveText('Visualiser');
  const dock = await page.getByTestId('dock').boundingBox();
  const hint = await page.locator('#first-run-hint').boundingBox();
  const bar = await page.locator('#transport').boundingBox();
  expect(dock.y + dock.height).toBeLessThanOrEqual(hint.y + 0.5);
  expect(hint.y + hint.height).toBeLessThanOrEqual(bar.y + 0.5);
  // The piano roll fills the inside of the visualiser's window.
  const inside = await body(page, 'visualiser').evaluate(el => ({ width: el.clientWidth, height: el.clientHeight }));
  const drawn = await roll(page).boundingBox();
  expect(drawn.width).toBeCloseTo(inside.width, 0);
  expect(drawn.height).toBeCloseTo(inside.height, 0);
});

test('a panel opens as a window beside the visualiser, and the piano roll narrows to make room', async ({ page }) => {
  await open(page);
  const full = (await roll(page).boundingBox()).width;

  await page.getByTestId('capture-toggle').click();

  await expect(tab(page, 'library')).toHaveText('Library');
  await expect(page.getByTestId('capture-panel')).toBeVisible();
  const drawn = await roll(page).boundingBox();
  const library = await body(page, 'library').boundingBox();
  expect(drawn.width).toBeLessThan(full - 100);
  expect(drawn.x + drawn.width).toBeLessThanOrEqual(library.x + 0.5);
  // A column of about a third of the dock, not GoldenLayout's even share.
  const dock = await page.getByTestId('dock').boundingBox();
  expect(library.width / dock.width).toBeCloseTo(0.32, 1);
});

test('a second panel joins the first one as a tab of its stack, in front', async ({ page }) => {
  await open(page);
  await page.getByTestId('capture-toggle').click();
  await page.getByTestId('results-toggle').click();

  expect(await stackOf(page, 'results')).toBe(await stackOf(page, 'library'));
  await expect(tab(page, 'results')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('results-panel')).toBeVisible();
  await expect(page.getByTestId('capture-panel')).toBeHidden();
});

test("a window's button or key closes it when it is in front, and the visualiser fills the dock again", async ({ page }) => {
  await open(page);
  const full = (await roll(page).boundingBox()).width;

  await page.getByTestId('transcript-toggle').click();
  await expect(tab(page, 'transcript')).toBeVisible();
  await page.getByTestId('transcript-toggle').click();
  await expect(tab(page, 'transcript')).toHaveCount(0);

  await page.keyboard.press('l');
  await expect(tab(page, 'library')).toBeVisible();
  await page.keyboard.press('l');
  await expect(tab(page, 'library')).toHaveCount(0);
  await expect.poll(async () => (await roll(page).boundingBox()).width).toBeCloseTo(full, 0);
});

test('a button brings its window to the front when another tab is over it, rather than closing it', async ({ page }) => {
  await open(page);
  await page.getByTestId('capture-toggle').click();
  await page.getByTestId('results-toggle').click();

  await page.getByTestId('capture-toggle').click();

  await expect(tab(page, 'library')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('capture-panel')).toBeVisible();
});

test("a tab's ✕ closes its window, and what the window held is there when it opens again", async ({ page }) => {
  await open(page);
  await page.getByTestId('results-toggle').click();
  await page.getByTestId('results-panel').evaluate(el => { el.dataset.kept = 'yes'; });

  await tab(page, 'results').locator('.lm_close_tab').click();
  await expect(tab(page, 'results')).toHaveCount(0);
  await expect(page.getByTestId('results-panel')).toBeHidden();

  await page.getByTestId('results-toggle').click();
  await expect(page.getByTestId('results-panel')).toBeVisible();
  await expect(page.getByTestId('results-panel')).toHaveAttribute('data-kept', 'yes');
});

test("a closed window's panel waits in the page, hidden, so what reaches for it still finds it", async ({ page }) => {
  await open(page);
  await page.getByTestId('results-toggle').click();
  await tab(page, 'results').locator('.lm_close_tab').click();
  await expect(tab(page, 'results')).toHaveCount(0);

  expect(await page.evaluate(() => {
    const fetch = document.querySelector('[data-testid="fetch-latest"]');
    return Boolean(fetch) && document.getElementById('parked').contains(fetch);
  })).toBe(true);
  await expect(page.getByTestId('fetch-latest')).toBeHidden();
});

test('the visualiser cannot be closed: its tab has no ✕, and Delete on it leaves it', async ({ page }) => {
  await open(page);

  await expect(tab(page, 'visualiser').locator('.lm_close_tab')).toBeHidden();
  await tab(page, 'visualiser').focus();
  await page.keyboard.press('Delete');
  await expect(tab(page, 'visualiser')).toBeVisible();
});

test('a window that can be closed closes by Delete on its tab', async ({ page }) => {
  await open(page);
  await page.getByTestId('transcript-toggle').click();

  await tab(page, 'transcript').focus();
  await page.keyboard.press('Delete');

  await expect(tab(page, 'transcript')).toHaveCount(0);
});

test('every window carries its id, its tab names it, and none of them pops out', async ({ page }) => {
  await open(page);
  for (const button of ['capture-toggle', 'results-toggle', 'transcript-toggle']) {
    await page.getByTestId(button).click();
  }

  for (const [id, title] of [['visualiser', 'Visualiser'], ['library', 'Library'],
                             ['results', 'Results'], ['transcript', 'Transcript']]) {
    await expect(tab(page, id)).toHaveAttribute('role', 'tab');
    await expect(tab(page, id)).toHaveAttribute('aria-label', title);
    await expect(tab(page, id)).toHaveAttribute('aria-controls', `panelbody-${id}`);
    await expect(body(page, id)).toHaveAttribute('role', 'tabpanel');
  }
  await expect(page.locator('.lm_popout:visible')).toHaveCount(0);
});

test('the arrangement is kept across a reload, and Reset layout puts back the visualiser alone', async ({ page }) => {
  await open(page);
  await page.getByTestId('transcript-toggle').click();
  await page.getByTestId('capture-toggle').click();
  await expect.poll(() => saved(page)).toContain('"library"');

  await page.reload();
  await expect(tab(page, 'transcript')).toBeVisible();
  await expect(tab(page, 'library')).toHaveAttribute('aria-selected', 'true');

  await page.getByTestId('panels-button').click();
  await page.getByRole('menuitem', { name: 'Reset layout' }).click();
  await expect(page.locator('.lm_tab')).toHaveCount(1);
  await page.reload();
  await expect(page.locator('.lm_tab')).toHaveCount(1);
});

const UNUSABLE = [
  ['is not JSON', '{', 'it is not JSON'],
  ['names a window this version lacks', JSON.stringify({ root: { type: 'row', content: [
    { type: 'stack', content: [{ type: 'component', componentType: 'visualiser', id: 'visualiser' }] },
    { type: 'stack', content: [{ type: 'component', componentType: 'mixer', id: 'mixer' }] },
  ] } }), 'which this version does not have'],
  ['has no visualiser', JSON.stringify({ root: { type: 'stack', content: [
    { type: 'component', componentType: 'library', id: 'library' },
  ] } }), 'it has no Visualiser'],
  ['shows a window twice', JSON.stringify({ root: { type: 'row', content: [
    { type: 'stack', content: [{ type: 'component', componentType: 'visualiser', id: 'visualiser' }] },
    { type: 'stack', content: [{ type: 'component', componentType: 'library', id: 'library' },
                               { type: 'component', componentType: 'library', id: 'library' }] },
  ] } }), 'it shows library twice'],
  ['GoldenLayout refuses', JSON.stringify({ root: { type: 'row', content: [
    { type: 'stack', size: 'lots', content: [{ type: 'component', componentType: 'visualiser', id: 'visualiser' }] },
  ] } }), 'GoldenLayout refused it'],
];

for (const [what, raw, why] of UNUSABLE) {
  test(`a saved arrangement that ${what} is dropped for the default, and the page says why`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    await seed(page, raw);

    await open(page);

    await expect(page.locator('.lm_tab')).toHaveCount(1);
    await expect(page.getByTestId('layout-note')).toContainText(why);
    expect(await saved(page)).not.toBe(raw);
    expect(errors).toEqual([]);
  });
}

test('the Panels menu lists every window, says which are closed, and opens one', async ({ page }) => {
  await open(page);
  await page.getByTestId('capture-toggle').click();

  await page.getByTestId('panels-button').click();

  const items = page.locator('#panels-menu [data-panel]');
  await expect(items.locator('.pm-name')).toHaveText(['Visualiser', 'Library', 'Results', 'Transcript', 'Voice']);
  await expect(page.locator('#panels-menu [data-panel].closed')).toHaveCount(3);
  await expect(page.locator('#panels-menu [data-panel="library"]')).not.toHaveClass(/closed/);
  await page.locator('#panels-menu [data-panel="transcript"]').click();
  await expect(page.locator('#panels-menu')).toBeHidden();
  await expect(tab(page, 'transcript')).toHaveAttribute('aria-selected', 'true');
});

test('the Panels menu by keyboard: arrows move, and Escape closes the menu and leaves the windows', async ({ page }) => {
  await open(page);
  await page.getByTestId('capture-toggle').click();
  const items = page.locator('#panels-menu [role="menuitem"]');

  await page.getByTestId('panels-button').focus();
  await page.keyboard.press('Enter');
  await expect(items.first()).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(items.nth(1)).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.getByRole('menuitem', { name: 'Reset layout' })).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(page.locator('#panels-menu')).toBeHidden();
  await expect(page.getByTestId('panels-button')).toBeFocused();
  await expect(tab(page, 'library')).toBeVisible();
});

test("a click outside the Panels menu closes it, and the click that opened it does not", async ({ page }) => {
  await open(page);

  await page.getByTestId('panels-button').click();
  await page.waitForTimeout(50);
  await expect(page.locator('#panels-menu')).toBeVisible();
  await page.mouse.click(200, 200);
  await expect(page.locator('#panels-menu')).toBeHidden();
});

test('dismissing the first-run hint gives the dock its room at once', async ({ page }) => {
  await open(page);
  const before = await body(page, 'visualiser').evaluate(el => el.clientHeight);
  const hint = (await page.locator('#first-run-hint').boundingBox()).height;

  await page.locator('#hint-dismiss').click();

  await expect.poll(() => body(page, 'visualiser').evaluate(el => el.clientHeight), { timeout: 500 })
    .toBeCloseTo(before + hint, 0);
});

test("the dock follows the window's size at once", async ({ page }) => {
  await open(page);

  await page.setViewportSize({ width: 900, height: 700 });

  const inside = () => body(page, 'visualiser').evaluate(el => el.clientWidth);
  await expect.poll(inside, { timeout: 500 }).toBeGreaterThan(890);
  await expect.poll(async () => (await roll(page).boundingBox()).width, { timeout: 500 }).toBeCloseTo(await inside(), 0);
});

test('readSavedLayout: nothing saved, a layout to load, or why it cannot be', async ({ page }) => {
  await page.goto('/');
  const read = await page.evaluate(async () => {
    const { readSavedLayout } = await import('/joe/layout/saved_layout.js');
    const { DEFAULT_LAYOUT } = await import('/joe/layout/default_layout.js');
    const panel = (id, more = {}) => ({ type: 'component', componentType: id, id, title: id, ...more });
    const stack = (...ids) => ({ type: 'stack', content: ids.map(id => panel(id)) });
    const layout = root => JSON.stringify({ root });
    const why = raw => readSavedLayout(raw).why;
    const usable = readSavedLayout(layout({ type: 'row', content: [
      { type: 'stack', content: [panel('visualiser', { title: 'Old', isClosable: true })] },
      stack('library', 'results'),
    ] }));
    return {
      none: [readSavedLayout(null).kind, readSavedLayout(undefined).kind, readSavedLayout('').kind],
      default: readSavedLayout(JSON.stringify(DEFAULT_LAYOUT)).kind,
      usable: usable.kind,
      // The registry's title and closability, whatever was saved; today's settings.
      visualiser: usable.config.root.content[0].content[0],
      popout: usable.config.header.popout,
      notJson: why('{'),
      notLayout: why('[]'),
      noRoot: why('{}'),
      popouts: why(JSON.stringify({ root: stack('visualiser'), openPopouts: [{}] })),
      unknown: why(layout({ type: 'row', content: [stack('visualiser'), stack('mixer')] })),
      notUnderId: why(layout({ type: 'stack', content: [panel('visualiser', { id: 'roll' })] })),
      twice: why(layout({ type: 'row', content: [stack('visualiser'), stack('voice', 'voice')] })),
      noVisualiser: why(layout(stack('library'))),
      emptyRow: why(layout({ type: 'row', content: [] })),
      unknownKind: why(layout({ type: 'grid', content: [stack('visualiser')] })),
      stackOfRows: why(layout({ type: 'stack', content: [{ type: 'row', content: [stack('visualiser')] }] })),
    };
  });

  expect(read).toEqual({
    none: ['none', 'none', 'none'],
    default: 'usable',
    usable: 'usable',
    visualiser: { type: 'component', componentType: 'visualiser', id: 'visualiser', title: 'Visualiser', isClosable: false },
    popout: false,
    notJson: 'it is not JSON',
    notLayout: 'it is not a layout',
    noRoot: 'it has no windows in it',
    popouts: 'it has windows popped out of the page',
    unknown: 'it names "mixer", which this version does not have',
    notUnderId: 'its Visualiser window is not under its id',
    twice: 'it shows voice twice',
    noVisualiser: 'it has no Visualiser',
    emptyRow: 'it has an empty row',
    unknownKind: 'it has an item of a kind GoldenLayout does not know ("grid")',
    stackOfRows: 'it has a stack holding something other than windows',
  });
});
