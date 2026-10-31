const { test, expect } = require('@playwright/test');

// The whole spoken exchange, docked beside the piano roll. The history, the
// stream and both vocabularies are scripted rather than served by joe or qmcp.
function sse(events) {
  return events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', at: 2000 + i, ...e })}\n\n`).join('');
}

const HISTORY = {
  kept: true,
  entries: [
    { kind: 'said', text: 'Ready. What should be done?', at: 1000 },
    { kind: 'take', take: 't1', text: 'deploy to the pi', source: 'voice', confidence: 0.52, at: 1002,
      label: 'misheard', outcome: 'recorded', audio: 'capture_1.wav',
      segments: [{ index: 0, words: ['deploy', 'vox', 'to', 'the', 'pi'], struck: [1], start: 0.1, end: 1.6 }] },
    { kind: 'said', text: 'Agree or again?', reason: 'confirm', at: 1004 },
  ],
};

const ASKING = {
  phrases: [{ key: 'conversation.stop', says: 'End the conversation', phrases: ['stop listening'], words: [] }],
  projects: { qm: { says: 'The constitution', terms: ['qm'], checks: [
    { name: 'gates', says: 'Whether the gates page matches its document', phrases: ['check the gates'],
      command: 'uv run --frozen qm gates --check handbook/gates.md' }] } },
};

async function script(page, { events = [], history = HISTORY, asking = ASKING, historyDelay = 0 } = {}) {
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse(events) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route(url => url.pathname === '/api/voice/history', async route => {
    if (historyDelay) await new Promise(done => setTimeout(done, historyDelay));
    await route.fulfill({ json: history });
  });
  await page.route(url => url.pathname === '/api/voice/vocabulary', route => route.fulfill({ json: {
    phrases: [{ key: 'take.scratch', says: 'Strike this segment and the one before it', phrases: ['scratch that'] }] } }));
  await page.route(url => url.pathname === '/v1/voice/vocabulary', route =>
    asking ? route.fulfill({ json: asking }) : route.fulfill({ status: 503, body: '' }));
}

test('T opens the whole transcript, oldest first, with strikes, confidence and labels', async ({ page }) => {
  await script(page);
  await page.goto('/');
  const pane = page.getByTestId('transcript-pane');
  await expect(pane).toBeHidden();

  await page.keyboard.press('t');

  await expect(pane).toBeVisible();
  const entries = pane.getByTestId('transcript-entries').locator('.tp-entry');
  await expect(entries).toHaveCount(3);
  await expect(entries.locator('.tp-who')).toHaveText(['Asked', 'Heard', 'Asked']);
  await expect(entries.nth(1).locator('.tp-word')).toHaveText(['deploy', 'vox', 'to', 'the', 'pi']);
  await expect(entries.nth(1).locator('.tp-word.is-struck')).toHaveText(['vox']);
  await expect(entries.nth(1).locator('.tp-conf')).toHaveText('sure 52%');
  await expect(entries.nth(1).locator('.tp-label')).toHaveText('misheard');
  await expect(entries.nth(2).locator('.tp-text')).toHaveText('Agree or again?');
});

test('the pane closes with ×, opens from the transport, and is remembered across a reload', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.getByTestId('transcript-toggle').click();
  await expect(page.getByTestId('transcript-pane')).toBeVisible();
  await expect(page.locator('body')).toHaveClass(/transcript-open/);

  await page.reload();
  await expect(page.getByTestId('transcript-pane')).toBeVisible();
  await expect(page.getByTestId('transcript-entries').locator('.tp-entry')).toHaveCount(3);

  await page.getByTestId('transcript-close').click();
  await expect(page.getByTestId('transcript-pane')).toBeHidden();
  await expect(page.locator('body')).not.toHaveClass(/transcript-open/);
});

test('what is asked and the take being written arrive live', async ({ page }) => {
  await script(page, { events: [
    { state: 'speaking', text: 'Anything else?' },
    { state: 'listening' },
    { state: 'transcript', take: 't2', text: 'run the tests in vox', segments: [
      { index: 0, words: ['run', 'the', 'tests', 'in', 'vox'], struck: [], pending: false },
      { index: 1, words: [], struck: [], pending: true }] },
    { state: 'note', text: 'The last take is marked misheard.' },
  ] });
  await page.goto('/');
  await page.keyboard.press('t');

  const entries = page.getByTestId('transcript-entries').locator('.tp-entry');
  await expect(entries).toHaveCount(6);
  await expect(entries.nth(3).locator('.tp-text')).toHaveText('Anything else?');
  await expect(entries.nth(4)).toHaveClass(/is-live/);
  await expect(entries.nth(4).locator('.tp-word')).toHaveText(['run', 'the', 'tests', 'in', 'vox', '…']);
  await expect(entries.nth(5).locator('.tp-who')).toHaveText('joe');
  // The stream ends and the panel reconnects, and is sent the same events again.
  await page.waitForTimeout(2600);
  await expect(entries).toHaveCount(6);
});

test('what can be said lists the conversation, its checks and joe', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('transcript-say-toggle').click();

  const say = page.getByTestId('transcript-say');
  await expect(say.locator('h3')).toHaveText(['To the conversation', 'Checks, run after approve',
                                              'To joe, inside a take']);
  await expect(say).toContainText('“stop listening”');
  await expect(say).toContainText('runs uv run --frozen qm gates --check handbook/gates.md');
  await expect(say).toContainText('“scratch that”');
});

test('without the conversation running, joe\'s words are still listed', async ({ page }) => {
  await script(page, { asking: null });
  await page.goto('/');
  await page.keyboard.press('t');
  await page.getByTestId('transcript-say-toggle').click();

  const say = page.getByTestId('transcript-say');
  await expect(say).toContainText('appear here while it is running');
  await expect(say).toContainText('“scratch that”');
});

test('T typed into a field opens nothing', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'typing';
    document.body.append(field);
  });
  await page.locator('#typing').press('t');

  await expect(page.getByTestId('transcript-pane')).toBeHidden();
});

test('a history that arrives after the stream keeps what streamed in', async ({ page }) => {
  await script(page, { historyDelay: 800, events: [
    { state: 'speaking', text: 'Anything else?' },
    { state: 'transcript', take: 't2', text: 'run the tests in vox', segments: [
      { index: 0, words: ['run', 'the', 'tests', 'in', 'vox'], struck: [], pending: false }] },
  ] });
  await page.goto('/');
  await page.keyboard.press('t');

  const entries = page.getByTestId('transcript-entries').locator('.tp-entry');
  await expect(entries).toHaveCount(5);
  await expect(entries.nth(3).locator('.tp-text')).toHaveText('Anything else?');
  await expect(entries.nth(4).locator('.tp-word')).toHaveText(['run', 'the', 'tests', 'in', 'vox']);
  await page.waitForTimeout(2600);  // past a reconnect, which sends the events again
  await expect(entries).toHaveCount(5);
});

// The stream's second connection, held until `release()`, carries a note, so the
// pane is drawn again after whatever the test opened.
async function noteLater(page) {
  let connections = 0;
  let release;
  const released = new Promise(done => { release = done; });
  await page.route('**/api/voice/conversation', async route => {
    connections += 1;
    if (connections > 1) await released;
    const events = connections > 1 ? [{ state: 'note', text: 'Loud enough.', at: 3000 }] : [];
    await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse(events) });
  });
  return release;
}

test('the first-run hint sits below the pane, not over its last lines', async ({ page }) => {
  await script(page);
  await page.goto('/');
  await page.keyboard.press('t');
  const pane = page.getByTestId('transcript-pane');
  const hint = page.locator('#first-run-hint');
  await expect(hint).toBeVisible();

  const paneBottom = async () => (await pane.boundingBox()).y + (await pane.boundingBox()).height;
  expect(await paneBottom()).toBeLessThanOrEqual((await hint.boundingBox()).y + 0.5);

  await page.locator('#hint-dismiss').click();
  await expect(hint).toBeHidden();
  const viewport = page.viewportSize();
  expect(await paneBottom()).toBeCloseTo(viewport.height - 48, 0);
});

// A take that heard nothing: no words in its segments, no text.
const QUIET = { kind: 'take', source: 'voice', text: '', segments: [{ index: 0, words: [], struck: [], start: 0, end: 1 }] };

test('takes in a row that heard nothing fold into one line, which opens and stays open', async ({ page }) => {
  const history = { kept: true, entries: [
    { kind: 'said', text: 'What should be done?', at: 1000 },
    { ...QUIET, take: 'q1', at: 1001 },
    { ...QUIET, take: 'q2', at: 1002, segments: [] },
    { ...QUIET, take: 'q3', at: 1003 },
    { kind: 'take', take: 'k1', text: 'yes', source: 'key', segments: [], at: 1004 },
    { ...QUIET, take: 'q4', at: 1005 },
  ] };
  await script(page, { history });
  const release = await noteLater(page);
  await page.goto('/');
  await page.keyboard.press('t');

  const folds = page.getByTestId('transcript-fold');
  await expect(folds).toHaveText(['3 takes, nothing heard', '1 take, nothing heard']);
  const lines = page.getByTestId('transcript-entries').locator(':scope > .tp-entry');
  await expect(lines.locator('.tp-who')).toHaveText(['Asked', 'Heard']);
  await expect(lines.nth(1).locator('.tp-text')).toHaveText('yes');
  const run = page.locator('.tp-fold-items').first();
  await expect(run).toBeHidden();

  await folds.first().click();
  await expect(folds.first()).toHaveAttribute('aria-expanded', 'true');
  await expect(run).toBeVisible();
  await expect(run.locator('.tp-entry')).toHaveCount(3);

  release();
  await expect(page.locator('.tp-note')).toHaveCount(1, { timeout: 10_000 });
  await expect(page.locator('.tp-fold-items').first()).toBeVisible();

  await folds.first().click();
  await expect(page.locator('.tp-fold-items').first()).toBeHidden();
});

test('a long question shows three lines until opened, and stays open', async ({ page }) => {
  const long = 'Run in qmcp: cross-check whether the local model tool and the files agree. '.repeat(8).trim();
  const history = { kept: true, entries: [
    { kind: 'said', text: long, at: 1000 },
    { kind: 'said', text: 'Approve or hold?', at: 1001 },
  ] };
  await script(page, { history });
  const release = await noteLater(page);
  await page.goto('/');
  await page.keyboard.press('t');

  const asks = page.getByTestId('transcript-entries').locator('.tp-said');
  const text = asks.first().locator('.tp-text');
  const more = page.getByTestId('transcript-more');
  await expect(more).toHaveCount(1);  // the short question has none
  await expect(more).toHaveText('more');
  await expect(text).toHaveText(long);  // all of it is there, for a reader of the text
  const clipped = el => el.scrollHeight > el.clientHeight + 1;
  expect(await text.evaluate(clipped)).toBe(true);
  expect(await text.evaluate(el => el.clientHeight / parseFloat(getComputedStyle(el).lineHeight))).toBeLessThan(3.5);

  await more.click();
  await expect(more).toHaveText('less');
  await expect(more).toHaveAttribute('aria-expanded', 'true');
  expect(await text.evaluate(clipped)).toBe(false);

  release();
  await expect(page.locator('.tp-note')).toHaveCount(1, { timeout: 10_000 });
  await expect(page.getByTestId('transcript-more')).toHaveText('less');
  expect(await asks.first().locator('.tp-text').evaluate(clipped)).toBe(false);
});

test('the transcript names each day where it changes: today, yesterday, then the date', async ({ page }) => {
  const now = Date.now() / 1000;
  const history = { kept: true, entries: [
    { kind: 'said', text: 'Two days ago.', at: now - 2 * 86400 },
    { kind: 'said', text: 'Again two days ago.', at: now - 2 * 86400 + 5 },
    { kind: 'said', text: 'Yesterday.', at: now - 86400 },
    { ...QUIET, take: 'q1', at: now - 86400 + 5 },
    { kind: 'said', text: 'A minute ago.', at: now - 60 },
  ] };
  await script(page, { history });
  await page.goto('/');
  await page.keyboard.press('t');

  const older = await page.evaluate(at => new Date(at * 1000).toLocaleDateString([],
    { weekday: 'short', day: 'numeric', month: 'short' }), now - 2 * 86400);
  const lines = page.getByTestId('transcript-entries').locator(':scope > li');
  await expect(lines).toHaveClass([/tp-day/, /tp-said/, /tp-said/, /tp-day/, /tp-said/, /tp-fold/, /tp-day/, /tp-said/]);
  await expect(page.getByTestId('transcript-day')).toHaveText([older, 'Yesterday', 'Today']);
});

test('a day this year is named without its year, and one in another year with it', async ({ page }) => {
  await page.goto('/');
  const said = await page.evaluate(async () => {
    const { dayLabel } = await import('/joe/components/TranscriptPane.js');
    const now = new Date(2026, 0, 2, 9);
    return [dayLabel(new Date(2026, 0, 2, 0, 1), now), dayLabel(new Date(2026, 0, 1, 23, 59), now),
            dayLabel(new Date(2025, 11, 31, 12), now).includes('2025'),
            dayLabel(new Date(2026, 0, 2, 9), new Date(2026, 2, 1, 9)).includes('2026')];
  });

  expect(said).toEqual(['Today', 'Yesterday', true, false]);
});
