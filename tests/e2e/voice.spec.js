const { test, expect } = require('@playwright/test');

// The conversation stream, scripted. The page reads it as it would read joe's.
function sse(events, levels = []) {
  const lines = events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', ...e })}\n\n`);
  const levelLines = levels.map(l => `event: level\ndata: ${JSON.stringify(l)}\n\n`);
  return lines.concat(levelLines).join('');
}

async function serve(page, events, levels) {
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
      body: sse(events, levels),
    }));
}

const EXCHANGE = [
  { state: 'speaking', text: 'Voice check. Say approve or hold.' },
  { state: 'listening' },
  { state: 'hearing' },
  { state: 'pausing' },
  { state: 'transcribing' },
  { state: 'heard', text: 'approve' },
  { state: 'recorded', text: 'approve' },
];

test('the panel stays out of the way until a conversation starts', async ({ page }) => {
  await serve(page, []);
  await page.goto('/');
  await page.waitForSelector('canvas');

  await expect(page.getByTestId('voice-panel')).toBeHidden();
});

test('a whole exchange reads in order, ending on what was recorded', async ({ page }) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await serve(page, EXCHANGE);
  await page.goto('/');

  const panel = page.getByTestId('voice-panel');
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute('data-state', 'recorded');
  await expect(page.getByTestId('voice-label')).toHaveText('Recorded');

  const log = page.getByTestId('voice-log');
  await expect(log.locator('li')).toHaveText([
    'Voice check. Say approve or hold.',
    '“approve”',
    'Recorded: approve',
  ]);
  // The track ends on the answer, every step before it done.
  await expect(page.locator('.voice-track li.is-current')).toHaveText('Answer');
  await expect(page.locator('.voice-track li.is-done')).toHaveCount(5);
  expect(errors).toHaveLength(0);
});

test('a re-ask says why it is asking again', async ({ page }) => {
  await serve(page, [
    { state: 'speaking', text: 'Voice check. Say approve or hold.' },
    { state: 'listening' },
    { state: 'heard', text: 'banana' },
    { state: 'speaking', text: 'I heard: banana. Say approve or hold.', reason: 'nomatch' },
  ]);
  await page.goto('/');

  await expect(page.getByTestId('voice-panel')).toHaveAttribute('data-state', 'speaking');
  await expect(page.getByTestId('voice-hint')).toHaveText('Asking again: that matched no option');
});

test('the microphone level shows only while the microphone is open', async ({ page }) => {
  await serve(page, [{ state: 'hearing' }], [{ rms: 0.008, threshold: 0.004 }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-panel')).toHaveAttribute('data-state', 'hearing');
  await expect(page.locator('.voice-level')).toBeVisible();
  // At the threshold's double the bar is full; at the threshold it is half.
  await expect(page.locator('.voice-level-fill')).toHaveAttribute('style', /width: 100%/);
});

test('every state looks different from every other', async ({ page }) => {
  const states = ['speaking', 'listening', 'hearing', 'pausing', 'transcribing',
                  'heard', 'no_speech', 'recorded', 'gave_up', 'idle'];
  const seen = [];
  for (const state of states) {
    await page.unroute('**/api/voice/conversation');
    await serve(page, [{ state, text: state === 'heard' ? 'hold' : '' }]);
    await page.goto('/');
    const panel = page.getByTestId('voice-panel');
    await expect(panel).toHaveAttribute('data-state', state);
    seen.push(await panel.evaluate(el => ({
      state: el.dataset.state,
      label: el.querySelector('.voice-label').textContent,
      colour: getComputedStyle(el).borderLeftColor,
    })));
  }

  const labels  = new Set(seen.map(s => s.label));
  const colours = new Set(seen.map(s => s.colour));
  expect(labels.size, JSON.stringify(seen)).toBe(states.length);
  expect(colours.size, JSON.stringify(seen)).toBe(states.length);
});
