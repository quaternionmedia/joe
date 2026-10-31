const { test, expect } = require('@playwright/test');
const { readFileSync } = require('fs');
const { join } = require('path');

const fixtureJson = JSON.parse(
  readFileSync(join(__dirname, 'fixtures/Process_Data_fixture.json'), 'utf-8')
);
const fixtureBuffer = Buffer.from(JSON.stringify(fixtureJson));

// Helper: open the results panel via the toggle button
async function openResultsPanel(page) {
  await page.getByTestId('results-toggle').click();
  await page.waitForTimeout(400); // allow slide-in animation
}

// ─── Results panel visibility ─────────────────────────────────────────────────

test('results panel is off-screen on load', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');

  const panel = page.getByTestId('results-panel');
  const box   = await panel.boundingBox();
  const vw    = await page.evaluate(() => window.innerWidth);

  // Panel should be translated fully off the right edge
  expect(box.x).toBeGreaterThanOrEqual(vw);
});

test('results toggle button opens the results panel', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  const panel = page.getByTestId('results-panel');
  const box   = await panel.boundingBox();
  const vw    = await page.evaluate(() => window.innerWidth);

  // Panel should now be on-screen
  expect(box.x).toBeLessThan(vw);
  expect(errors).toHaveLength(0);
});

test('file input is present inside the open results panel', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  await expect(page.getByTestId('file-input')).toBeAttached();
});

// ─── JSON loading + piano roll ────────────────────────────────────────────────

test('results meta shows note count after load', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  await page.getByTestId('file-input').setInputFiles({
    name:     'Process_Data_fixture.json',
    mimeType: 'application/json',
    buffer:   fixtureBuffer,
  });

  const meta = page.getByTestId('results-meta');
  await expect(meta).toContainText('Notes:');
  await expect(meta).toContainText('Iteration:');
});

// ─── Error handling ───────────────────────────────────────────────────────────

test('malformed JSON shows load-error element and does not crash', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  await page.getByTestId('file-input').setInputFiles({
    name:     'bad.json',
    mimeType: 'application/json',
    buffer:   Buffer.from('{invalid json'),
  });

  await expect(page.getByTestId('load-error')).toBeVisible({ timeout: 2000 });
  expect(errors).toHaveLength(0);
});

// ─── Era panel ────────────────────────────────────────────────────────────────

test('era panel shows correct genre after first ArrowRight', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(450);

  await expect(page.getByTestId('era-genre')).toHaveText('Baroque');
  expect(errors).toHaveLength(0);
});

test('era panel genre updates on second ArrowRight', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(450);
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(450);

  await expect(page.getByTestId('era-genre')).toHaveText('Classical');
});

test('era panel clamps at index 0 on repeated ArrowLeft', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');

  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('ArrowLeft');
  }
  await page.waitForTimeout(450);

  // At index 0 (placeholder), genre is empty string
  await expect(page.getByTestId('era-genre')).toHaveText('');
});

// ─── Panel close ─────────────────────────────────────────────────────────────

test('results panel closes on second toggle click', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');

  await openResultsPanel(page);

  // Click again to close
  await page.getByTestId('results-toggle').click();
  await page.waitForTimeout(400);

  const box = await page.getByTestId('results-panel').boundingBox();
  const vw  = await page.evaluate(() => window.innerWidth);
  expect(box.x).toBeGreaterThanOrEqual(vw);
});

// ─── Fetch Latest ─────────────────────────────────────────────────────────────

test('Fetch Latest button loads results and shows note count', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  // Mock the API before page load
  await page.route('**/api/results/latest', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify(fixtureJson),
  }));

  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  await page.getByTestId('fetch-latest').click();

  // Results meta should show note count
  await expect(page.getByTestId('results-meta')).toContainText('Notes:');

  // Piano roll canvas should be visible
  await expect(page.getByTestId('piano-roll-canvas')).toBeVisible();

  expect(errors).toHaveLength(0);
});

// ─── Canvas mode badge ────────────────────────────────────────────────────────

test('Canvas mode badge shows RESULTS after loading notes from file input', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');
  await openResultsPanel(page);

  await page.getByTestId('file-input').setInputFiles({
    name:     'Process_Data_fixture.json',
    mimeType: 'application/json',
    buffer:   fixtureBuffer,
  });

  await page.waitForTimeout(300);

  // canvas-mode badge should read RESULTS
  const badge = page.locator('#canvas-mode');
  await expect(badge).toHaveText('RESULTS', { timeout: 2000 });

  expect(errors).toHaveLength(0);
});

test("the panel's heading reads on one line, clear of its buttons", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto('/');
  await page.getByTestId('results-toggle').click();
  const heading = page.locator('#results-panel h2');
  await expect(heading).toBeVisible();

  const box = await heading.boundingBox();
  const line = await heading.evaluate(el => parseFloat(getComputedStyle(el).lineHeight)
    || parseFloat(getComputedStyle(el).fontSize) * 1.4);
  expect(box.height).toBeLessThan(line * 1.5);
  const actions = await page.locator('.results-actions').boundingBox();
  const overlap = box.x < actions.x + actions.width && actions.x < box.x + box.width
    && box.y < actions.y + actions.height && actions.y < box.y + box.height;
  expect(overlap).toBe(false);
});
