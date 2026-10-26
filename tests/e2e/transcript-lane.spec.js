const { test, expect } = require('@playwright/test');

// A take shown on the visualiser: its recording on the transport, its words on
// the piano roll's timeline. History and recording are scripted.
function sse(events) {
  return events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', at: 2000 + i, ...e })}\n\n`).join('');
}

// Two seconds of silence as a WAV, so the audio element learns a duration.
function wav(seconds = 2, rate = 8000) {
  const samples = seconds * rate;
  const buf = Buffer.alloc(44 + samples * 2);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + samples * 2, 4); buf.write('WAVE', 8);
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write('data', 36); buf.writeUInt32LE(samples * 2, 40);
  return buf;
}

const HISTORY = {
  kept: true,
  entries: [
    { kind: 'said', text: 'What should be done?', at: 1000 },
    { kind: 'take', take: 'a1b2c3', text: 'deploy to the pi', source: 'voice', at: 1002, audio: 'capture_1.wav',
      segments: [{ index: 0, words: ['deploy', 'vox', 'to', 'the', 'pi'], struck: [1], start: 0.2, end: 1.2 }] },
    { kind: 'take', take: 'd4e5f6', text: 'approve', source: 'key', at: 1004, segments: [] },
  ],
};

// `kept: false` answers every recording as joe does for a take whose file is gone.
async function script(page, { history = HISTORY, kept = true } = {}) {
  const fetched = [];
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse([]) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route(url => url.pathname === '/api/voice/history', route => route.fulfill({ json: history }));
  await page.route(url => url.pathname.startsWith('/api/voice/takes/'), route => {
    fetched.push(new URL(route.request().url()).pathname);
    if (!kept) return route.fulfill({ status: 404, json: { detail: 'no recording kept for take a1b2c3' } });
    route.fulfill({ status: 200, headers: { 'content-type': 'audio/wav' }, body: wav() });
  });
  return fetched;
}

// The scrubber moved by hand to `t` seconds, once the recording's length is known.
async function scrubTo(page, t) {
  await page.getByTestId('transport-scrub').evaluate((el, v) => {
    el.value = String(v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, t);
}

const litWord = page => page.getByTestId('piano-roll-canvas').getAttribute('data-current-word');

test('Show puts the take on the transport and its standing words on the timeline', async ({ page }) => {
  const fetched = await script(page);
  await page.goto('/');
  await page.keyboard.press('t');

  const shows = page.getByTestId('transcript-show');
  await expect(shows).toHaveCount(1);  // a take by key has no recording to show
  await shows.click();

  await expect(page.getByTestId('transport-name')).toHaveText('take a1b2c3');
  await expect(page.getByTestId('piano-roll-canvas'))
    .toHaveAttribute('aria-label', 'Words on the timeline: deploy to the pi');
  await expect.poll(() => fetched).toContain('/api/voice/takes/a1b2c3/audio');
  await expect(page.getByTestId('transport-duration')).toHaveText('0:02');
  await expect(page.getByTestId('transport-note')).toBeHidden();
});

test('ejecting the recording takes its words off the timeline', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('transcript-show').click();
  await expect(page.getByTestId('piano-roll-canvas')).toHaveAttribute('aria-label', /deploy/);

  await page.getByTestId('transport-eject').click();

  await expect(page.getByTestId('piano-roll-canvas')).not.toHaveAttribute('aria-label', /.+/);
});

test('words share their segment evenly and a struck one keeps its place', async ({ page }) => {
  await page.goto('/');
  const placed = await page.evaluate(async () => {
    const { takeWords } = await import('/joe/components/takeWords.js');
    return takeWords({ segments: [
      { words: ['a', 'b'], struck: [1], start: 1, end: 2 },
      { words: ['skipped'], struck: [], start: null, end: null },
      { words: [], struck: [], start: 3, end: 4 },
    ] });
  });

  expect(placed).toEqual([
    { text: 'a', start: 1, end: 1.5, struck: false },
    { text: 'b', start: 1.5, end: 2, struck: true },
  ]);
});

// The take in HISTORY places deploy 0.2–0.4, vox 0.4–0.6 (struck), to 0.6–0.8,
// the 0.8–1.0 and pi 1.0–1.2, in a recording two seconds long.

test('the lit word is the one under the playhead, and a struck word is never lit', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('transcript-show').click();
  await expect(page.getByTestId('transport-duration')).toHaveText('0:02');
  await page.getByTestId('transport-stop').click();

  for (const [t, word] of [[0.1, null], [0.3, 'deploy'], [0.5, null], [0.7, 'to'],
                           [0.9, 'the'], [1.1, 'pi'], [1.5, null]]) {
    await scrubTo(page, t);
    expect(await litWord(page), `lit at ${t} s`).toBe(word);
  }
});

test('while the take plays, the lit word follows it word by word', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('piano-roll-canvas').evaluate(canvas => {
    window.litWords = [];
    new MutationObserver(() => window.litWords.push(canvas.getAttribute('data-current-word')))
      .observe(canvas, { attributes: true, attributeFilter: ['data-current-word'] });
  });

  await page.getByTestId('transcript-show').click();
  await expect(page.getByTestId('transport-play')).toHaveText('Pause');
  await expect(page.getByTestId('transport-play')).toHaveText('Play', { timeout: 10_000 });

  const seen = await page.evaluate(() => window.litWords);
  expect(seen.filter(Boolean)).toEqual(['deploy', 'to', 'the', 'pi']);
  expect(seen.at(-1)).toBeNull();
});

test('a standing word is lit from its start up to its end', async ({ page }) => {
  await page.goto('/');
  const lit = await page.evaluate(async () => {
    const { litWord } = await import('/joe/components/takeWords.js');
    const words = [{ start: 1, end: 2, struck: false }, { start: 2, end: 3, struck: true },
                   { start: 3, end: 4, struck: false }];
    return [0.5, 1, 1.99, 2, 2.5, 3, 4].map(t => litWord(words, t));
  });

  expect(lit).toEqual([-1, 0, 0, -1, -1, 2, -1]);
});

test('a word too long for its place is cut and ends in an ellipsis', async ({ page }) => {
  await page.goto('/');
  const fitted = await page.evaluate(async () => {
    const { fitText } = await import('/joe/components/MainCanvas.js');
    const measure = s => s.length * 10;  // ten pixels a character
    return [fitText('to', 45, measure), fitText('whether', 45, measure),
            fitText('whether', 12, measure), fitText('whether', 5, measure)];
  });

  expect(fitted).toEqual(['to', 'whe…', '…', '']);
});

test('a clipped word is shown whole under the pointer, and a word that fits is not', async ({ page }) => {
  const history = { kept: true, entries: [
    { kind: 'take', take: 'a1b2c3', text: 'extraordinarily ok', source: 'voice', at: 1002, audio: 'capture_1.wav',
      segments: [
        { index: 0, words: ['extraordinarily'], struck: [], start: 0, end: 0.05 },
        { index: 1, words: ['ok'], struck: [], start: 1, end: 2 },
      ] },
  ] };
  await script(page, { history });
  await page.goto('/');
  await page.locator('#hint-dismiss').click();
  await page.keyboard.press('t');
  await page.getByTestId('transcript-show').click();
  await page.getByTestId('transcript-close').click();
  await expect(page.getByTestId('transport-duration')).toHaveText('0:02');

  // The lane runs the width of the canvas past its 28 px of labels, 26 px tall,
  // 6 px above the canvas's bottom edge; the recording is two seconds long.
  const box = await page.getByTestId('piano-roll-canvas').boundingBox();
  const at = t => box.x + 28 + (t / 2) * (box.width - 28);
  const laneMid = box.y + box.height - 6 - 13;
  const tip = page.getByTestId('lane-tip');

  await page.mouse.move(at(0.025), laneMid);
  await expect(tip).toBeVisible();
  await expect(tip).toHaveText('extraordinarily');

  await page.mouse.move(at(1.5), laneMid);
  await expect(tip).toBeHidden();

  await page.mouse.move(at(0.025), laneMid - 60);
  await expect(tip).toBeHidden();
});

test('a take whose recording is not kept is laid out, and the transport stays stopped and says so', async ({ page }) => {
  const fetched = await script(page, { kept: false });
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('transcript-show').click();

  await expect(page.getByTestId('transport-note')).toHaveText('recording not kept');
  await expect(page.getByTestId('transport-play')).toHaveText('Play');
  await expect(page.getByTestId('piano-roll-canvas'))
    .toHaveAttribute('aria-label', 'Words on the timeline: deploy to the pi');
  expect(fetched).toContain('/api/voice/takes/a1b2c3/audio');

  // Play has nothing to play, so it does not claim to.
  await page.getByTestId('transport-play').click();
  await expect(page.getByTestId('transport-play')).toHaveText('Play');

  await page.getByTestId('transport-eject').click();
  await expect(page.getByTestId('transport-note')).toBeHidden();
});
