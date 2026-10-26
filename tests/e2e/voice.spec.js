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

test('the Voice window stays closed until a conversation starts', { tag: '@voice-loop' }, async ({ page }) => {
  await serve(page, []);
  const connected = page.waitForRequest('**/api/voice/conversation');
  await page.goto('/');
  await connected;
  await page.waitForSelector('canvas');

  await expect(page.locator('#paneltab-voice')).toHaveCount(0);
  await expect(page.getByTestId('voice-panel')).toBeHidden();
});

test('a Voice window opened from the Panels menu stays open while no conversation runs', { tag: '@voice-loop' }, async ({ page }) => {
  await page.clock.install();
  await serve(page, []);
  let polls = 0;
  await page.route(url => url.pathname === '/v1/human/requests', route => {
    polls += 1;
    route.fulfill({ json: { requests: [], count: 0 } });
  });
  await page.goto('/');
  await page.getByTestId('panels-button').click();
  await page.locator('#panels-menu [data-panel="voice"]').click();
  await expect(page.locator('#paneltab-voice')).toBeVisible();

  const before = polls;
  await page.clock.fastForward(60_000);   // the queue's polls, each finding nothing

  await expect.poll(() => polls).toBeGreaterThan(before);
  await expect(page.locator('#paneltab-voice')).toBeVisible();
});

test('a conversation opens the Voice window above the transcript, so both can be read', { tag: '@voice-loop' }, async ({ page }) => {
  // The stream held until the transcript is open.
  let release;
  const held = new Promise(done => { release = done; });
  await page.route('**/api/voice/conversation', async route => {
    await held;
    await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' },
                          body: sse([{ state: 'speaking', text: 'Anything else?' }]) });
  });
  await page.goto('/');
  await page.getByTestId('transcript-toggle').click();
  await expect(page.locator('#paneltab-transcript')).toBeVisible();

  release();

  await expect(page.getByTestId('voice-panel')).toBeVisible();
  await expect(page.getByTestId('transcript-pane')).toBeVisible();
  const voice = await page.locator('#panelbody-voice').boundingBox();
  const transcript = await page.locator('#panelbody-transcript').boundingBox();
  expect(voice.y + voice.height).toBeLessThanOrEqual(transcript.y);
});

test('a conversation leaves a tab the person put in front of the Voice window where it is', { tag: '@voice-loop' }, async ({ page }) => {
  // The Voice window a tab behind the transcript's, as a person might have dragged it.
  const window = id => ({ type: 'component', componentType: id, id, title: id });
  await page.addInitScript(layout => {
    if (sessionStorage.getItem('seeded')) return;
    sessionStorage.setItem('seeded', '1');
    localStorage.setItem('joe.layout.v1', layout);
  }, JSON.stringify({ root: { type: 'row', content: [
    { type: 'stack', content: [window('visualiser')] },
    { type: 'stack', activeItemIndex: 0, content: [window('transcript'), window('voice')] },
  ] } }));
  await serve(page, [{ state: 'speaking', text: 'Anything else?' }, { state: 'listening' }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-label')).toHaveText('Your turn');
  await expect(page.locator('#paneltab-transcript')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('transcript-pane')).toBeVisible();
});

test('a whole exchange reads in order, ending on what was recorded', { tag: '@voice-loop' }, async ({ page }) => {
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

test('a re-ask says why it is asking again', { tag: '@voice-loop' }, async ({ page }) => {
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

test('the microphone level shows only while the microphone is open', { tag: '@voice-loop' }, async ({ page }) => {
  await serve(page, [{ state: 'hearing' }], [{ rms: 0.008, threshold: 0.004 }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-panel')).toHaveAttribute('data-state', 'hearing');
  await expect(page.locator('.voice-level')).toBeVisible();
  // At the threshold's double the bar is full; at the threshold it is half.
  await expect(page.locator('.voice-level-fill')).toHaveAttribute('style', /width: 100%/);
});

test("a conversation's first state shows in its own colour at once, not faded in from another", { tag: '@voice-loop' }, async ({ page }) => {
  await page.addInitScript(() => {
    window.__faded = [];
    document.addEventListener('transitionrun', e => {
      if (e.target.id === 'voice-panel') window.__faded.push(e.propertyName);
    }, true);
  });
  await serve(page, [{ state: 'speaking', text: 'Anything else?' }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-panel')).toHaveAttribute('data-state', 'speaking');
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.__faded)).toEqual([]);
});

test('every state looks different from every other', { tag: '@voice-loop' }, async ({ page }) => {
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
