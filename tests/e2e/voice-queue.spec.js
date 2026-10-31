const { test, expect } = require('@playwright/test');

// qmcp's human queue, scripted. The page reaches it through the dev proxy's /v1.
const LAUNCH = { id: 'demo', prompt: 'Launch the audit?', options: ['approve', 'hold'], status: 'pending' };
const DEPLOY = { id: 'later', prompt: 'Deploy?', options: ['approve', 'reject'], status: 'pending' };

async function script(page, { lists, post = { status: 202, body: { request_id: 'demo', running: true } }, runs = [] }) {
  const calls = { lists: 0, listQueries: [], posts: [], runs: 0, log: [] };
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' }));
  await page.route(url => url.pathname === '/v1/human/requests', route => {
    const requests = lists[Math.min(calls.lists, lists.length - 1)];
    calls.lists += 1;
    calls.log.push(['list', Date.now()]);
    calls.listQueries.push(new URL(route.request().url()).searchParams);
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ requests, count: requests.length }) });
  });
  await page.route(url => /^\/v1\/human\/requests\/[^/]+\/voice$/.test(url.pathname), route => {
    calls.posts.push(new URL(route.request().url()).pathname);
    route.fulfill({ status: post.status, contentType: 'application/json', body: JSON.stringify(post.body) });
  });
  await page.route(url => url.pathname === '/v1/human/voice', route => {
    const status = runs[Math.min(calls.runs, runs.length - 1)];
    calls.runs += 1;
    calls.log.push([status.running ? 'running' : 'ended', Date.now()]);
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(status) });
  });
  return calls;
}

test('nothing waiting leaves the Voice window closed', async ({ page }) => {
  const calls = await script(page, { lists: [[]] });
  await page.goto('/');
  await page.waitForSelector('canvas');
  await expect.poll(() => calls.lists).toBeGreaterThan(0);

  await expect(page.locator('#paneltab-voice')).toHaveCount(0);
  await expect(page.getByTestId('voice-panel')).toBeHidden();
});

test('the oldest waiting request is offered with its options', async ({ page }) => {
  const calls = await script(page, { lists: [[LAUNCH, DEPLOY]] });
  await page.goto('/');

  await expect(page.getByTestId('voice-panel')).toBeVisible();
  await expect(page.getByTestId('voice-queue-count')).toHaveText('2 waiting on you');
  await expect(page.getByTestId('voice-queue-prompt')).toHaveText('Launch the audit?  (approve / hold)');
  await expect(page.getByTestId('voice-answer')).toBeEnabled();
  // Pending only, oldest first: qmcp lists newest first unless asked.
  expect(calls.listQueries[0].get('status')).toBe('pending');
  expect(calls.listQueries[0].get('oldest_first')).toBe('true');
});

test('answering asks qmcp once, waits for the run, then reads the queue again', async ({ page }) => {
  const calls = await script(page, {
    lists: [[LAUNCH], []],
    runs: [{ running: true }, { running: false, exit_code: 0, output: ["  demo answered 'approve' (by voice)."] }],
  });
  await page.goto('/');
  await expect(page.getByTestId('voice-answer')).toBeEnabled();

  await page.getByTestId('voice-answer').click();
  // One conversation at a time: the button is off the moment it is pressed,
  // read without waiting -- a waiting assertion also passes once the run has
  // ended and the empty queue has hidden the button.
  expect(await page.getByTestId('voice-answer').isDisabled()).toBe(true);

  await expect(page.getByTestId('voice-queue')).toBeHidden({ timeout: 10000 });
  expect(calls.posts).toEqual(['/v1/human/requests/demo/voice']);
  // The queue is read again as soon as the run ends, not at the next poll,
  // which is seconds later and would hide a missing re-read.
  const ended = calls.log.findIndex(([kind]) => kind === 'ended');
  const next = calls.log.slice(ended + 1).find(([kind]) => kind === 'list');
  expect(next, JSON.stringify(calls.log)).toBeTruthy();
  expect(next[1] - calls.log[ended][1]).toBeLessThan(1500);
});

test('a run that fails shows the command\'s own last words', async ({ page }) => {
  const words = "No speech engine answers at http://127.0.0.1:8000. Start it in the engine's checkout: uv run joe backend";
  await script(page, {
    lists: [[LAUNCH]],
    runs: [{ running: false, exit_code: 1, output: ['Checking...', words] }],
  });
  await page.goto('/');
  await page.getByTestId('voice-answer').click();

  await expect(page.getByTestId('voice-queue-note')).toHaveText(words, { timeout: 10000 });
  await expect(page.getByTestId('voice-answer')).toBeEnabled();
});

test('a refusal shows qmcp\'s reason', async ({ page }) => {
  const detail = "A conversation is already running, for 'other'. One at a time: there is one microphone.";
  await script(page, { lists: [[LAUNCH]], post: { status: 409, body: { detail } } });
  await page.goto('/');
  await page.getByTestId('voice-answer').click();

  await expect(page.getByTestId('voice-queue-note')).toHaveText(detail);
});

// The page's visibility, as a browser sets it when the tab is hidden or shown.
const showPage = (page, state) => page.evaluate(state => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}, state);

test('while qmcp cannot be reached, Instruct by voice says so, and a hidden page asks nothing', async ({ page }) => {
  let asked = 0;
  await page.clock.install();
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' }));
  // What the dev proxy answers when nothing listens where qmcp should.
  await page.route(url => url.pathname === '/v1/human/requests', route => {
    asked += 1;
    route.fulfill({ status: 500, body: '' });
  });
  await page.goto('/');

  const instruct = page.getByTestId('voice-instruct');
  await expect(instruct).toHaveClass(/is-unreachable/);
  await expect(instruct).toHaveAttribute('title', /qmcp is not reachable/);
  await expect.poll(() => asked).toBe(1);

  await showPage(page, 'hidden');
  await page.clock.fastForward(10 * 60_000);
  await page.waitForTimeout(500);   // a request the timers started would have arrived by now
  expect(asked).toBe(1);

  await showPage(page, 'visible');
  await expect.poll(() => asked).toBe(2);
});

test('once qmcp answers, Instruct by voice is itself again', async ({ page }) => {
  let reachable = false;
  await page.clock.install();
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' }));
  await page.route(url => url.pathname === '/v1/human/requests', route => reachable
    ? route.fulfill({ json: { requests: [], count: 0 } })
    : route.fulfill({ status: 500, body: '' }));
  await page.goto('/');
  const instruct = page.getByTestId('voice-instruct');
  await expect(instruct).toHaveClass(/is-unreachable/);

  reachable = true;
  await page.clock.fastForward(60_000);
  await expect(instruct).not.toHaveClass(/is-unreachable/);
  await expect(instruct).toHaveAttribute('title', '');
});
