const { test, expect } = require('@playwright/test');

// qmcp's instruction inbox, scripted. The page reaches it through the dev
// proxy's /v1, as it reaches the human queue, which is empty unless a spec
// puts something in it.
const ROTATE = { id: 'r1', text: 'Rotate the vectors nightly', project: 'rad', status: 'recorded', source: 'voice' };
const VAGUE  = { id: 'v1', text: 'Tidy the docs', project: null, status: 'unresolved', source: 'voice' };
const LAUNCH = { id: 'demo', prompt: 'Launch the audit?', options: ['approve', 'hold'], status: 'pending' };

const STARTED = { status: 202, body: { kind: 'instruction', request_id: null, running: true } };

async function script(page, { post = STARTED, runs = [], latest = [ROTATE], pending = [], unreachable = false }) {
  const calls = { posts: [], runs: 0, lists: [], log: [] };
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' }));
  await page.route(url => url.pathname === '/v1/human/requests', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ requests: pending, count: pending.length }) }));
  await page.route(url => url.pathname === '/v1/instructions/voice', route => {
    if (route.request().method() === 'POST') {
      calls.posts.push(new URL(route.request().url()).pathname);
      if (unreachable) return route.abort('connectionrefused');
      return route.fulfill({ status: post.status, contentType: 'application/json', body: JSON.stringify(post.body) });
    }
    const status = runs[Math.min(calls.runs, runs.length - 1)];
    calls.runs += 1;
    calls.log.push([status.running ? 'running' : 'ended', Date.now()]);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(status) });
  });
  await page.route(url => url.pathname === '/v1/instructions', route => {
    calls.lists.push(new URL(route.request().url()).searchParams);
    calls.log.push(['list', Date.now()]);
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ instructions: latest, count: latest.length }) });
  });
  return calls;
}

test('the button is at hand while the panel is out of the way', async ({ page }) => {
  await script(page, {});
  await page.goto('/');
  await page.waitForSelector('canvas');

  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
  await expect(page.getByTestId('voice-panel')).toBeHidden();
});

// Seen to fail: with the POST sent to `/instructions/voic`, the mock never saw
// it, the dev proxy answered 500 and the recorded text stayed empty (every test
// below but the first went red the same way); with `_follow()` skipped, no run
// was ever read as 'ended' and the timing assertion threw; with `row.status`
// replaced by `row.source`, the status read 'voice'.
test('instructing posts once, waits for the run, then shows what was recorded', async ({ page }) => {
  const calls = await script(page, {
    runs: [{ running: true, kind: 'instruction' }, { running: false, kind: 'instruction', exit_code: 0, output: ['  r1  rad  recorded'] }],
  });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();
  // One conversation at a time: the button is off the moment it is pressed,
  // read without waiting -- a waiting assertion also passes once the run has
  // ended and the button is back on.
  expect(await page.getByTestId('voice-instruct').isDisabled()).toBe(true);
  await expect(page.getByTestId('voice-panel')).toBeVisible();

  await expect(page.getByTestId('voice-instruct-text')).toHaveText('“Rotate the vectors nightly”', { timeout: 10000 });
  await expect(page.getByTestId('voice-instruct-project')).toHaveText('rad');
  await expect(page.getByTestId('voice-instruct-status')).toHaveText('recorded');
  await expect(page.getByTestId('voice-instruct-note')).toBeHidden();
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
  expect(calls.posts).toEqual(['/v1/instructions/voice']);
  // The newest row only, and read once the run has ended, not before.
  expect(calls.lists[0].get('limit')).toBe('1');
  const ended = calls.log.findIndex(([kind]) => kind === 'ended');
  const next = calls.log.slice(ended + 1).find(([kind]) => kind === 'list');
  expect(next, JSON.stringify(calls.log)).toBeTruthy();
  expect(next[1] - calls.log[ended][1]).toBeLessThan(1500);
});

// Seen to fail: with `row.project || 'no project'` reduced to `row.project`,
// the project read as empty text.
test('an instruction that named no project is shown as such, unresolved', async ({ page }) => {
  await script(page, {
    runs: [{ running: false, kind: 'instruction', exit_code: 0, output: [] }],
    latest: [VAGUE],
  });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-text')).toHaveText('“Tidy the docs”', { timeout: 10000 });
  await expect(page.getByTestId('voice-instruct-project')).toHaveText('no project');
  await expect(page.getByTestId('voice-instruct-status')).toHaveText('unresolved');
});

// Seen to fail: with the `if (!row)` branch removed, `row.text` threw and the
// note read 'qmcp could not be reached: Cannot read properties of undefined'.
test('a run that ends with the inbox empty says so', async ({ page }) => {
  await script(page, {
    runs: [{ running: false, kind: 'instruction', exit_code: 0, output: [] }],
    latest: [],
  });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-note'))
    .toHaveText('The conversation ended, and the inbox is empty.', { timeout: 10000 });
  await expect(page.getByTestId('voice-instruct-latest')).toBeHidden();
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
});

// Seen to fail: with `this._latest.hidden = true` dropped from the start of
// instruct(), the first conversation's row stayed on screen beside the second
// one's failure, as if that run had recorded it.
test('a second conversation that fails does not show the first one\'s row', async ({ page }) => {
  const words = "No usable instruction after 3 attempts; last heard ''";
  await script(page, {
    runs: [
      { running: false, kind: 'instruction', exit_code: 0, output: ['  r1  rad  recorded'] },
      { running: false, kind: 'instruction', exit_code: 1, output: ['Checking...', words] },
    ],
  });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();
  await expect(page.getByTestId('voice-instruct-text')).toHaveText('“Rotate the vectors nightly”', { timeout: 10000 });
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();

  await page.getByTestId('voice-instruct').click();
  await expect(page.getByTestId('voice-instruct-note')).toHaveText(words, { timeout: 10000 });
  // Read without waiting: the outcome steps aside later and takes the row with
  // it, so a waiting assertion could pass for that reason instead.
  expect(await page.getByTestId('voice-instruct-latest').isHidden()).toBe(true);
});

// Seen to fail: with VoiceInstruct.mount replacing the panel's keepOpen rather
// than chaining it (`() => this.running || this._holding`), the panel went
// away with a request still waiting in the queue: panelHidden read true. The
// two states are read in one evaluation at the instant the outcome leaves,
// because a retrying assertion that the panel is visible also passes under
// that mutation: the queue's next poll reveals the panel again within seconds,
// after the user has watched it vanish.
test('the outcome stepping aside leaves the panel to the queue', async ({ page }) => {
  await script(page, {
    pending: [LAUNCH],
    runs: [{ running: false, kind: 'instruction', exit_code: 0, output: [] }],
  });
  await page.goto('/');
  await expect(page.getByTestId('voice-answer')).toBeEnabled();
  await page.getByTestId('voice-instruct').click();
  await expect(page.getByTestId('voice-instruct-text')).toHaveText('“Rotate the vectors nightly”', { timeout: 10000 });

  const left = await page.waitForFunction(() => {
    const outcome = document.querySelector('[data-testid="voice-instruct-outcome"]');
    if (!outcome.hidden) return null;
    return { panelHidden: document.querySelector('[data-testid="voice-panel"]').hidden };
  }, null, { timeout: 15000 });
  expect(await left.jsonValue()).toEqual({ panelHidden: false });
  await expect(page.getByTestId('voice-queue-prompt')).toHaveText('Launch the audit?  (approve / hold)');
});

// Seen to fail: with the `exit_code !== 0` branch removed, the newest row was
// shown as if the failed run had recorded it and the note stayed empty.
test('a run that fails shows the command\'s own last words, not the inbox', async ({ page }) => {
  const words = "No usable instruction after 3 attempts; last heard ''";
  await script(page, {
    runs: [{ running: false, kind: 'instruction', exit_code: 1, output: ['Checking...', words] }],
  });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-note')).toHaveText(words, { timeout: 10000 });
  await expect(page.getByTestId('voice-instruct-latest')).toBeHidden();
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
});

// Seen to fail: with `body.detail ||` removed, the note read 'qmcp answered 409'.
test('a refusal shows qmcp\'s reason', async ({ page }) => {
  const detail = "A conversation is already running, for 'demo'. One at a time: there is one microphone.";
  await script(page, { post: { status: 409, body: { detail } } });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-note')).toHaveText(detail);
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
});

// Seen to fail: with the 404 branch removed, the note read the server's own
// 'Not Found', which says nothing about an inbox.
test('a qmcp without the inbox gets a note, and the page goes on', async ({ page }) => {
  await script(page, { post: { status: 404, body: { detail: 'Not Found' } } });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-note')).toContainText('no instruction inbox');
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
});

// Seen to fail: with the catch replaced by one that cleared the note, nothing
// was shown and the test timed out waiting for it.
test('a qmcp that cannot be reached is said so', async ({ page }) => {
  await script(page, { unreachable: true });
  await page.goto('/');
  await page.getByTestId('voice-instruct').click();

  await expect(page.getByTestId('voice-instruct-note')).toContainText('qmcp could not be reached');
  await expect(page.getByTestId('voice-instruct')).toBeEnabled();
});
