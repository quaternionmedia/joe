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

// ─── Scripts from the CDN ────────────────────────────────────────────────────

const CDN_SCRIPTS = {
  'https://cdn.jsdelivr.net/npm/p5@1.11.2/lib/p5.min.js': 'node_modules/p5/lib/p5.min.js',
  'https://cdn.jsdelivr.net/npm/p5@1.11.2/lib/addons/p5.sound.js': 'node_modules/p5/lib/addons/p5.sound.js',
};

test('each CDN script is held to the bytes of the p5 the lockfile installs', async () => {
  const { createHash } = require('crypto');
  const root = join(__dirname, '..', '..');
  const html = readFileSync(join(root, 'src', 'index.html'), 'utf-8');
  const tags = [...html.matchAll(/<script src="(https:[^"]+)"\s+integrity="([^"]+)"\s+crossorigin="anonymous">/g)];

  expect(Object.fromEntries(tags.map(([, src, integrity]) => [src, integrity]))).toEqual(
    Object.fromEntries(Object.entries(CDN_SCRIPTS).map(([src, file]) => [
      src, `sha384-${createHash('sha384').update(readFileSync(join(root, file))).digest('base64')}`,
    ])),
  );
  expect(html.match(/<script src="https:/g)).toHaveLength(tags.length);
});

test('p5 and p5.sound load from the CDN past their integrity check', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('canvas');

  expect(await page.evaluate(() => typeof window.p5)).toBe('function');
  expect(await page.evaluate(() => typeof window.p5.FFT)).toBe('function');
  expect(errors).toHaveLength(0);
});

// ─── The transport's scrubber ────────────────────────────────────────────────

for (const width of [1024, 1280]) {
  test(`the scrubber's knob clears the time readout at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 768 });
    await page.goto('/');
    const scrub = await page.getByTestId('transport-scrub').boundingBox();
    const time = await page.getByTestId('transport-time').boundingBox();

    expect(scrub.width).toBeGreaterThanOrEqual(60);
    expect(scrub.x + scrub.width).toBeLessThanOrEqual(time.x);

    // A loaded file's name gives way to the scrubber, and the bar stays within the window.
    await page.getByTestId('transport-name').evaluate(el => { el.textContent = 'a-recording-with-a-long-name.wav'; });
    const loaded = await page.getByTestId('transport-scrub').boundingBox();
    expect(loaded.width).toBeGreaterThanOrEqual(60);
    expect(await page.locator('#transport').evaluate(bar => bar.scrollWidth <= bar.clientWidth)).toBe(true);
  });
}

// ─── Where Live records from ─────────────────────────────────────────────────

test('the capture select says where Live records from, and what each choice is', async ({ page }) => {
  await page.goto('/');
  const select = page.getByRole('combobox', { name: 'Live records from' });
  await expect(select).toHaveAttribute('title', 'Where Live records from');
  await expect(select.locator('option')).toHaveText(['Browser mic', "joe's mic"]);
  await expect(select.locator('option[value="browser"]')).toHaveAttribute('title', /This browser's microphone/);
  await expect(select.locator('option[value="backend"]')).toHaveAttribute('title', /machine joe runs on/);
  await expect(page.locator('#first-run-hint')).toContainText("Browser mic or joe's mic + Live — record");
});

// ─── The specs' own servers ──────────────────────────────────────────────────

test("a spec's page reaches no backend the spec has not scripted", async ({ page }) => {
  await page.goto('/');

  // joe's API and qmcp's queue, through the page's own proxy: neither is a joe
  // or a qmcp that happens to be running on this machine.
  const answers = await page.evaluate(() => Promise.all(['/api/health', '/v1/human/requests'].map(async path => {
    const res = await fetch(path);
    return { path, status: res.status, text: await res.text() };
  })));
  for (const { path, status, text } of answers) {
    expect(status, path).toBe(503);
    expect(text, path).toContain('no backend in the specs');
  }
});
