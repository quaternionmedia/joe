const { test, expect } = require('@playwright/test');

// The take as it is written. The stream is scripted; strikes are recorded
// rather than served by joe.
function sse(events) {
  return events.map((e, i) =>
    `id: ${i + 1}\ndata: ${JSON.stringify({ seq: i + 1, text: '', ...e })}\n\n`).join('');
}

async function script(page, events) {
  const strikes = [];
  await page.route('**/api/voice/conversation', route =>
    route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: sse(events) }));
  await page.route(url => /^\/v1\/human\/requests/.test(url.pathname), route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"requests": [], "count": 0}' }));
  await page.route('**/api/voice/strike', route => {
    strikes.push(route.request().postDataJSON());
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  return strikes;
}

const WRITING = [
  { state: 'speaking', text: 'Ready. What should be done?' },
  { state: 'listening' },
  { state: 'hearing' },
  { state: 'transcript', take: 't1', text: 'deploy the vox build', segments: [
    { index: 0, words: ['deploy', 'the', 'vox', 'build'], struck: [2], pending: false },
    { index: 1, words: [], struck: [], pending: true },
  ] },
];

test('the take shows as it is written, a struck word crossed out and a pending segment marked', async ({ page }) => {
  await script(page, WRITING);
  await page.goto('/');

  const transcript = page.getByTestId('voice-transcript');
  await expect(transcript).toBeVisible();
  await expect(transcript.locator('.voice-word')).toHaveText(['deploy', 'the', 'vox', 'build']);
  await expect(transcript.locator('.voice-word.is-struck')).toHaveText(['vox']);
  await expect(transcript.locator('.voice-segment.is-pending')).toHaveText('…');
  // The words are not a turn: the label stays on what the microphone is doing.
  await expect(page.getByTestId('voice-label')).toHaveText('Hearing you');
});

test('clicking a word strikes it, and Backspace strikes the last one standing', async ({ page }) => {
  const strikes = await script(page, WRITING);
  await page.goto('/');
  await expect(page.getByTestId('voice-transcript').locator('.voice-word')).toHaveCount(4);

  await page.getByTestId('voice-transcript').locator('.voice-word', { hasText: 'build' }).click();
  await page.keyboard.press('Backspace');
  await expect.poll(() => strikes).toEqual([
    { take: 't1', segment: 0, word: 3 },
    { take: 't1', last: true },
  ]);
});

test('Backspace typed into a field strikes nothing', async ({ page }) => {
  const strikes = await script(page, WRITING);
  await page.goto('/');
  await expect(page.getByTestId('voice-transcript').locator('.voice-word')).toHaveCount(4);

  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'typing';
    field.value = 'abc';
    document.body.append(field);
  });
  await page.locator('#typing').press('Backspace');
  await page.waitForTimeout(300);
  expect(strikes).toEqual([]);
});
