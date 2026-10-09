const { test, expect } = require('@playwright/test');

// Answering the conversation without speaking. The stream is scripted; the
// routes a key or button reaches are recorded rather than served by joe.
function sse(events) {
  return events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', ...e })}\n\n`).join('');
}

async function script(page, events) {
  const sent = { answers: [], holds: [] };
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse(events) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route('**/api/voice/answer', route => {
    sent.answers.push(route.request().postDataJSON().text);
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"held": false, "answer_waiting": true}' });
  });
  await page.route('**/api/voice/hold', route => {
    sent.holds.push(route.request().postDataJSON().held);
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"held": false, "answer_waiting": false}' });
  });
  return sent;
}

const ASKED = [
  { state: 'speaking', text: 'Act on the instruction ... Say approve or hold.', options: ['approve', 'hold'] },
  { state: 'listening' },
];

test('a question offers its options as numbered buttons, and a click answers', async ({ page }) => {
  const sent = await script(page, ASKED);
  await page.goto('/');

  const options = page.getByTestId('voice-options');
  await expect(options).toBeVisible();
  await expect(options.locator('button')).toHaveText(['1 approve', '2 hold']);
  await options.locator('button[data-option="hold"]').click();
  await expect.poll(() => sent.answers).toEqual(['hold']);
});

test('the number keys answer by position, R repeats and Shift+Esc stops', async ({ page }) => {
  const sent = await script(page, ASKED);
  await page.goto('/');
  await expect(page.getByTestId('voice-options').locator('button')).toHaveCount(2);

  await page.keyboard.press('1');
  await page.keyboard.press('3');   // no third option: nothing is sent
  await page.keyboard.press('r');
  await page.keyboard.press('Escape');   // without Shift, nothing
  await page.keyboard.press('Shift+Escape');
  await expect.poll(() => sent.answers).toEqual(['approve', 'repeat', 'stop listening']);
});

test('holding the tilde key holds the turn open until it is released', async ({ page }) => {
  const sent = await script(page, ASKED);
  await page.goto('/');
  await expect(page.getByTestId('voice-panel')).toBeVisible();

  await page.keyboard.down('Backquote');
  await expect(page.getByTestId('voice-hold')).toHaveClass(/is-held/);
  await page.keyboard.down('Backquote');   // auto-repeat sends nothing more
  await page.keyboard.up('Backquote');
  await expect.poll(() => sent.holds).toEqual([true, false]);
  await expect(page.getByTestId('voice-hold')).not.toHaveClass(/is-held/);
});

test('keys typed into a field are not answers', async ({ page }) => {
  const sent = await script(page, ASKED);
  await page.goto('/');
  await expect(page.getByTestId('voice-options').locator('button')).toHaveCount(2);

  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'typing';
    document.body.append(field);
  });
  await page.locator('#typing').type('1r');
  await page.keyboard.press('Shift+Escape');
  await page.waitForTimeout(300);
  expect(sent.answers).toEqual([]);
});

test('the options go once the exchange has an outcome, and an answer by key is marked', async ({ page }) => {
  await script(page, [...ASKED, { state: 'heard', text: 'approve', source: 'key' },
                      { state: 'recorded', text: 'approve' }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-log')).toContainText('“approve” (key)');
  await expect(page.getByTestId('voice-options')).toBeHidden();
});

test('a window losing focus releases a held key, once, and sends nothing when none is held', async ({ page }) => {
  const sent = await script(page, ASKED);
  await page.goto('/');
  await expect(page.getByTestId('voice-panel')).toBeVisible();

  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  await page.keyboard.down('Backquote');
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  await page.keyboard.up('Backquote');   // already released by the blur
  await page.waitForTimeout(300);
  expect(sent.holds).toEqual([true, false]);
});

test('a question said again on request says so', async ({ page }) => {
  await script(page, [{ state: 'speaking', text: 'Say approve or hold.', options: ['approve', 'hold'], reason: 'repeat' }]);
  await page.goto('/');

  await expect(page.getByTestId('voice-hint')).toHaveText('Saying it again, as asked');
});
