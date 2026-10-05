const { test, expect } = require('@playwright/test');

// A take shown on the visualiser: its recording on the transport, its words on
// the piano roll's timeline. History and recording are scripted.
function sse(events) {
  return events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', ...e })}\n\n`).join('');
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

async function script(page) {
  const fetched = [];
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse([]) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route(url => url.pathname === '/api/voice/history', route => route.fulfill({ json: HISTORY }));
  await page.route(url => url.pathname.startsWith('/api/voice/takes/'), route => {
    fetched.push(new URL(route.request().url()).pathname);
    route.fulfill({ status: 200, headers: { 'content-type': 'audio/wav' }, body: wav() });
  });
  return fetched;
}

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
