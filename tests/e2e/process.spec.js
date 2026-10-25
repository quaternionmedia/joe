'use strict';
const { test, expect } = require('@playwright/test');
const { readFileSync } = require('fs');
const { join } = require('path');

const fixtureJson = JSON.parse(
  readFileSync(join(__dirname, 'fixtures/Process_Data_fixture.json'), 'utf-8')
);

// Minimal valid WAV (44-byte header, zero samples) so HTMLAudioElement accepts
// the src without an immediate error, letting onloadedmetadata fire.
const SILENT_WAV = Buffer.from([
  0x52,0x49,0x46,0x46, 0x24,0x00,0x00,0x00, // RIFF, chunk size 36
  0x57,0x41,0x56,0x45,                       // WAVE
  0x66,0x6D,0x74,0x20, 0x10,0x00,0x00,0x00, // fmt , subchunk size 16
  0x01,0x00,           // PCM
  0x01,0x00,           // 1 channel
  0x44,0xAC,0x00,0x00, // 44100 Hz sample rate
  0x88,0x58,0x01,0x00, // byte rate
  0x02,0x00,           // block align
  0x10,0x00,           // 16 bits per sample
  0x64,0x61,0x74,0x61, 0x00,0x00,0x00,0x00, // data, 0 bytes
]);

/**
 * Install route mocks for all API endpoints used by the app.
 * Must be called before page.goto() so the mocks are active when
 * CapturePanel.mount() calls _loadLibrary() on startup.
 *
 * Playwright tries routes in reverse registration order (the last one
 * registered wins), so the catch-all audio route goes first and the
 * more specific /api/audio/files route after it.
 */
async function mockApi(page, {
  filename       = 'test.wav',
  pipelineOk     = true,
  pipelineStderr = '',
} = {}) {
  // Audio file served to HTMLAudioElement (catch-all; registered first so
  // the /api/audio/files route below takes precedence)
  await page.route('**/api/audio/**', route => route.fulfill({
    status:      200,
    contentType: 'audio/wav',
    body:        SILENT_WAV,
  }));

  // Library file list (fetched on mount)
  await page.route('**/api/audio/files', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify([{ name: filename, size: 12345, mtime: 1700000000 }]),
  }));

  // Pipeline run (POST /api/run/{filename})
  await page.route('**/api/run/**', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify(
      pipelineOk
        ? { returncode: 0, stdout: 'ok', stderr: '' }
        : { returncode: 1, stdout: '', stderr: pipelineStderr || 'error' }
    ),
  }));

  // Latest result JSON (fetched by ResultsPanel.fetchLatest)
  await page.route('**/api/results/latest', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify(fixtureJson),
  }));
}

// ─── Process flow ─────────────────────────────────────────────────────────────

test('Library Process triggers pipeline and loads correct results', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await mockApi(page, { filename: 'test.wav' });
  await page.goto('/');
  await page.waitForSelector('canvas');

  // Open Library and wait for list to populate
  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="process"]', { timeout: 3000 });

  // Click Process on the library item
  await page.locator('[data-action="process"]').first().click();

  // The pipeline call and fetchLatest open the Results window
  await expect(page.getByTestId('results-panel')).toBeVisible();

  // Results meta should reflect fixture note count
  const meta = await page.getByTestId('results-meta').textContent();
  expect(meta).toMatch(/Notes:/);

  // Transport should display the processed filename
  await expect(page.getByTestId('transport-name')).toHaveText('test.wav', { timeout: 2000 });

  // Eject button should appear (file is now loaded)
  await expect(page.getByTestId('transport-eject')).toBeVisible();

  expect(errors).toHaveLength(0);
});

test('Pipeline failure does not open results panel or activate audio', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await mockApi(page, { filename: 'fail.wav', pipelineOk: false, pipelineStderr: 'Error: decode failed' });
  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="process"]', { timeout: 3000 });
  await page.locator('[data-action="process"]').first().click();

  // Give enough time for any (incorrect) async effects to run
  await page.waitForTimeout(600);

  // The Results window stays closed (no joe:resultsReady fired)
  await expect(page.getByTestId('results-panel')).toBeHidden();

  // Transport name should be empty — stale audio must NOT be activated
  await expect(page.getByTestId('transport-name')).toHaveText('');

  // Eject button must stay hidden
  await expect(page.getByTestId('transport-eject')).toBeHidden();

  // Error element should be visible with the pipeline stderr message
  await expect(page.getByTestId('capture-error')).toBeVisible();

  expect(errors).toHaveLength(0);
});

test('Unsupported format shows error and keeps results panel closed', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  // Catch-all audio route first, so the /api/audio/files route registered
  // after it takes precedence (last registered wins).
  await page.route('**/api/audio/**', route => route.fulfill({
    status:      200,
    contentType: 'application/octet-stream',
    body:        Buffer.from([]),
  }));
  await page.route('**/api/audio/files', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify([{ name: 'capture.xyz', size: 5000, mtime: 1700000000 }]),
  }));
  await page.route('**/api/run/**', route => route.fulfill({
    status:      200,
    contentType: 'application/json',
    body:        JSON.stringify({
      returncode: 1,
      stdout:     '',
      stderr:     "Format '.xyz' is not supported by the pipeline. Supported: .flac, .mp3, .ogg, .wav, .webm",
    }),
  }));

  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="process"]', { timeout: 3000 });
  await page.locator('[data-action="process"]').first().click();
  await page.waitForTimeout(400);

  // Error shown to user in the library panel
  await expect(page.getByTestId('capture-error')).toBeVisible();
  const errText = await page.getByTestId('capture-error').textContent();
  expect(errText).toMatch(/not supported/i);

  // The Results window stays closed
  await expect(page.getByTestId('results-panel')).toBeHidden();

  expect(errors).toHaveLength(0);
});

// ─── Library Play ─────────────────────────────────────────────────────────────

test('Library Play loads audio and highlights the active row', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await mockApi(page, { filename: 'test.wav' });
  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="play"]', { timeout: 3000 });
  await page.locator('[data-action="play"]').first().click();

  await page.waitForTimeout(500);

  // Transport name updated
  await expect(page.getByTestId('transport-name')).toHaveText('test.wav', { timeout: 2000 });

  // Eject button visible
  await expect(page.getByTestId('transport-eject')).toBeVisible();

  // Library row carries .lib-active
  const row = page.locator('[data-testid="capture-file-list"] li[data-name="test.wav"]');
  await expect(row).toHaveClass(/lib-active/);

  expect(errors).toHaveLength(0);
});

// ─── Eject ────────────────────────────────────────────────────────────────────

test('Eject clears transport name, hides button, and removes library highlight', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  await mockApi(page, { filename: 'test.wav' });
  await page.goto('/');
  await page.waitForSelector('canvas');

  // Load a file via Library Play
  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="play"]', { timeout: 3000 });
  await page.locator('[data-action="play"]').first().click();
  await page.waitForTimeout(300);

  // Verify loaded state
  await expect(page.getByTestId('transport-name')).toHaveText('test.wav');
  await expect(page.getByTestId('transport-eject')).toBeVisible();

  // Click eject
  await page.getByTestId('transport-eject').click();
  await page.waitForTimeout(200);

  // Transport cleared
  await expect(page.getByTestId('transport-name')).toHaveText('');
  await expect(page.getByTestId('transport-eject')).toBeHidden();

  // Library highlight removed
  const row = page.locator('[data-testid="capture-file-list"] li[data-name="test.wav"]');
  await expect(row).not.toHaveClass(/lib-active/);

  expect(errors).toHaveLength(0);
});

// ─── Library panel open/close ─────────────────────────────────────────────────

test('Library panel closes on second toggle click', async ({ page }) => {
  await mockApi(page, { filename: 'test.wav' });
  await page.goto('/');
  await page.waitForSelector('canvas');

  // Open
  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="play"]', { timeout: 3000 });
  const panel = page.getByTestId('capture-panel');
  await expect(panel).toBeVisible();

  // Close
  await page.getByTestId('capture-toggle').click();
  await expect(panel).toBeHidden();
  await expect(page.locator('#paneltab-library')).toHaveCount(0);
});

// ─── What the Library list shows ──────────────────────────────────────────────

test('A file name is shown as text, never as markup', async ({ page }) => {
  // A name is whatever Data/Audio/ holds; this page can drive joe's API.
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  const name = '<img src=x onerror="window.__ran=1">"quoted".wav';

  await mockApi(page, { filename: name });
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.getByTestId('capture-toggle').click();
  await page.waitForSelector('[data-action="play"]', { timeout: 3000 });

  const list = page.getByTestId('capture-file-list');
  await expect(list.locator('.lib-name')).toHaveText(name);
  await expect(list.locator('img')).toHaveCount(0);
  expect(await page.evaluate(() => window.__ran)).toBeUndefined();
  // The buttons carry the name itself, as the API needs it back.
  expect(await list.locator('[data-action="play"]').getAttribute('data-name')).toBe(name);
  expect(errors).toHaveLength(0);
});

test('A library joe does not serve says so, and what turning it on exposes', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  const detail = 'the audio library is off on this joe: JOE_ALLOW_LIBRARY=1 turns it on, for '
    + 'whatever can reach this port -- joe has no authentication (docs/security.md)';

  await page.route('**/api/audio/files', route => route.fulfill({
    status:      403,
    contentType: 'application/json',
    body:        JSON.stringify({ detail }),
  }));
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.getByTestId('capture-toggle').click();

  await expect(page.getByTestId('capture-file-list')).toHaveText('The library is off. Turning it on lets '
    + 'anything that reaches this port read and add recordings. docs/security.md');
  await expect(page.locator('[data-action="play"]')).toHaveCount(0);
  expect(errors).toHaveLength(0);
});
