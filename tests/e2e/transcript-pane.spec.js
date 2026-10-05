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

async function script(page, { events = [], history = HISTORY, asking = ASKING } = {}) {
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse(events) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route(url => url.pathname === '/api/voice/history', route => route.fulfill({ json: history }));
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
