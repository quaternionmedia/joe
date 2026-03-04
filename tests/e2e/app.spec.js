const { test, expect } = require('@playwright/test');
const { readFileSync } = require('fs');
const { join } = require('path');

const fixtureJson = JSON.parse(
  readFileSync(join(__dirname, 'fixtures/Process_Data_fixture.json'), 'utf-8')
);

// ─── Page load ───────────────────────────────────────────────────────────────

test('page loads and canvas is visible', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  expect(await page.isVisible('canvas')).toBe(true);
  expect(errors).toHaveLength(0);
});

// ─── "Joe, go!" button ───────────────────────────────────────────────────────

test('"Joe, go!" button is present and clickable', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  // Canonical testid selector + role as secondary assertion
  const button = page.getByTestId('start-button');
  await expect(button).toBeVisible();
  await expect(page.getByRole('button', { name: 'Joe, go!' })).toBeVisible();

  // Click — mic will be denied in headless; the app should not crash
  await button.click();

  expect(await page.isVisible('canvas')).toBe(true);
  expect(errors).toHaveLength(0);
});

// ─── Keyboard navigation ─────────────────────────────────────────────────────

test('arrow key navigation updates era panel and does not crash', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  // First ArrowRight → index 1 (Baroque)
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(450); // allow cross-fade animation
  await expect(page.getByTestId('era-genre')).toHaveText('Baroque');

  // Second ArrowRight → index 2 (Classical)
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(450);
  await expect(page.getByTestId('era-genre')).toHaveText('Classical');

  // Navigate back
  await page.keyboard.press('ArrowLeft');
  await page.waitForTimeout(450);
  await expect(page.getByTestId('era-genre')).toHaveText('Baroque');

  // Spam past the beginning — should clamp at index 0, not crash
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('ArrowLeft');
  }
  await page.waitForTimeout(450);

  expect(await page.isVisible('canvas')).toBe(true);
  expect(errors).toHaveLength(0);
});

// ─── Pipeline JSON smoke test ────────────────────────────────────────────────

test('Process_Data fixture has required backend contract keys', async ({ page }) => {
  await page.route('**/Process_Data_fixture.json', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixtureJson),
    });
  });

  await page.goto('/');

  const response = await page.evaluate(async () => {
    const res = await fetch('/Process_Data_fixture.json');
    return res.json();
  });

  expect(response).toHaveProperty('iteration');
  expect(response).toHaveProperty('audio');
  expect(response).toHaveProperty('min_duration');
  expect(response).toHaveProperty('fft_sizes');
  expect(response).toHaveProperty('chroma_threshold');
  expect(response).toHaveProperty('harmonic_threshold');
  expect(response).toHaveProperty('overtone_weights');

  const audioEntries = Object.values(response.audio);
  expect(audioEntries.length).toBeGreaterThan(0);
  const firstAudio = audioEntries[0];
  expect(firstAudio).toHaveProperty('name');
  expect(firstAudio).toHaveProperty('sr');
  expect(firstAudio).toHaveProperty('chroma');

  // All three transform types present in extended fixture
  expect(firstAudio.chroma).toHaveProperty('Raw');
  expect(firstAudio.chroma).toHaveProperty('Harmonic');
  expect(firstAudio.chroma).toHaveProperty('Percussive');
});
