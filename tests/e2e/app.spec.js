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

// ─── Transport initial state ──────────────────────────────────────────────────

test('Live button is disabled until Joe, go! is clicked', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  // Live toggle must be disabled on load (Web Audio context not started)
  const liveBtn = page.getByTestId('live-toggle');
  await expect(liveBtn).toBeDisabled();

  // After Joe, go! it should become enabled
  await page.getByTestId('start-button').click();
  await expect(liveBtn).toBeEnabled({ timeout: 2000 });

  expect(errors).toHaveLength(0);
});

test('Canvas mode badge is empty on initial load', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');

  // No recording or results — badge should be blank
  await expect(page.locator('#canvas-mode')).toHaveText('');
});
