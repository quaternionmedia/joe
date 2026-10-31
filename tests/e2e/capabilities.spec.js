const { test, expect } = require('@playwright/test');

// What a joe serves, read from /api/health: a control whose capability is off
// is greyed and names its setting, each panel says what is off in a sentence
// with a link, and the first-run hint keeps the steps that work.

const SECURITY_URL = 'https://github.com/quaternionmedia/joe/blob/main/docs/security.md';
const FRESH = { media: true, microphone: false, transcripts: false, library: false };
const ALL   = { media: true, microphone: true, transcripts: true, library: true };

// `allowed: null` is a joe that cannot be asked: no backend.
async function serve(page, allowed) {
  await page.route(url => url.pathname === '/api/health', route => allowed
    ? route.fulfill({ json: { status: 'ok', allowed } })
    : route.abort());
  const off = name => ({ detail: `${name} is off on this joe` });
  await page.route(url => url.pathname === '/api/audio/files', route => allowed?.library
    ? route.fulfill({ json: [] }) : route.fulfill({ status: 403, json: off('the audio library') }));
  await page.route(url => url.pathname === '/api/results/latest', route =>
    route.fulfill({ status: 403, json: off('the audio library') }));
  await page.route(url => url.pathname === '/api/voice/history', route => allowed?.transcripts
    ? route.fulfill({ json: { entries: [], kept: true } }) : route.fulfill({ status: 403, json: off('the transcripts') }));
  await page.route('**/api/voice/conversation', route => route.fulfill({ status: 403, json: off('the transcripts') }));
  await page.route(url => /^\/v1\//.test(url.pathname), route =>
    route.fulfill({ json: { requests: [], count: 0 } }));
}

// Nothing is greyed until /api/health has answered, so a spec that expects
// nothing greyed waits for the page to have read it: the page marks the
// Library button, greyed or not, once it has.
async function pageHasRead(page) {
  await expect(page.getByTestId('capture-toggle')).toHaveAttribute('data-own-title', /.*/);
}

test('a joe serving the media API alone greys Library, Transcript and Live, each naming its setting', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, FRESH);
  await page.goto('/');

  await expect(page.getByTestId('capture-toggle')).toHaveClass(/is-off/);
  await expect(page.getByTestId('capture-toggle'))
    .toHaveAttribute('title', 'Off on this joe: JOE_ALLOW_LIBRARY=1 turns it on');
  await expect(page.getByTestId('transcript-toggle'))
    .toHaveAttribute('title', 'Off on this joe: JOE_ALLOW_TRANSCRIPTS=1 turns it on');

  await page.getByTestId('start-button').click();
  const live = page.getByTestId('live-toggle');
  await expect(live).toBeDisabled();
  await expect(live).toHaveAttribute('title', 'Off on this joe: JOE_ALLOW_LIBRARY=1 turns it on');

  await page.getByTestId('capture-mode').selectOption('backend');
  await expect(live).toBeDisabled();
  await expect(live).toHaveAttribute('title',
    'Off on this joe: JOE_ALLOW_MICROPHONE=1 and JOE_ALLOW_LIBRARY=1 turns it on');
});

test('a joe serving everything greys nothing, and Live opens once audio starts', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, ALL);
  await page.goto('/');
  await pageHasRead(page);
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('[data-off]').length)).toBe(0);

  await expect(page.getByTestId('transcript-toggle')).toHaveAttribute('title', 'Transcript: the whole spoken exchange (T)');
  await expect(page.getByTestId('capture-toggle')).not.toHaveClass(/is-off/);
  await expect(page.getByTestId('live-toggle')).toBeDisabled();  // until Joe, go!
  await page.getByTestId('start-button').click();
  await expect(page.getByTestId('live-toggle')).toBeEnabled();
});

test('with no backend nothing is greyed: no backend is a normal way to run the page', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, null);
  await page.goto('/');
  await page.getByTestId('start-button').click();

  await expect(page.getByTestId('live-toggle')).toBeEnabled();
  await expect(page.getByTestId('capture-toggle')).not.toHaveClass(/is-off/);
  await expect(page.getByTestId('transcript-toggle')).not.toHaveClass(/is-off/);
});

test('the Library and the transcript each say what is off, in a sentence with a link', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, FRESH);
  await page.goto('/');

  await page.getByTestId('capture-toggle').click();
  const library = page.getByTestId('off-library');
  await expect(library).toHaveText('The library is off. Turning it on lets anything that reaches this port '
    + 'read and add recordings. docs/security.md');
  await expect(library.getByRole('link')).toHaveAttribute('href', SECURITY_URL);

  await page.keyboard.press('t');
  const transcripts = page.getByTestId('off-transcripts');
  await expect(transcripts).toHaveText('The transcripts are off. Turning them on lets anything that reaches '
    + 'this port read every conversation joe has heard. docs/security.md');
  await expect(transcripts.getByRole('link')).toHaveAttribute('href', SECURITY_URL);
});

test('Fetch Latest is greyed while the library is off, and a refusal it meets anyway says so', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, FRESH);
  await page.goto('/');
  await expect(page.getByTestId('fetch-latest')).toBeDisabled();
  await expect(page.getByTestId('fetch-latest'))
    .toHaveAttribute('title', 'Off on this joe: JOE_ALLOW_LIBRARY=1 turns it on');

  // A joe that cannot be asked greys nothing; the refusal is said where results would be.
  await page.unrouteAll();
  await serve(page, null);
  await page.goto('/');
  await page.getByTestId('results-toggle').click();
  await page.getByTestId('fetch-latest').click();
  await expect(page.getByTestId('load-error')).toBeVisible();
  await expect(page.getByTestId('load-error').getByTestId('off-library')).toContainText('The library is off.');
  await expect(page.getByTestId('load-error')).not.toContainText('Could not parse');
});

test('the first-run hint keeps the steps that work and says what --allow turns on', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, FRESH);
  await page.goto('/');

  const steps = page.locator('#first-run-hint .hint-step');
  await expect(steps).toHaveCount(1);
  await expect(steps).toHaveText('1. Joe, go! — start audio');
  const said = page.getByTestId('hint-off');
  await expect(said).toHaveText('--allow library turns on recording, the pipeline and results (docs/security.md)');
  await expect(said.getByRole('link')).toHaveAttribute('href', SECURITY_URL);
});

test('on a joe serving everything the first-run hint keeps all four steps', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, ALL);
  await page.goto('/');
  await pageHasRead(page);
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('[data-off]').length)).toBe(0);

  await expect(page.locator('#first-run-hint .hint-step')).toHaveCount(4);
  await expect(page.getByTestId('hint-off')).toBeHidden();
});

test('Live names only what its capture mode needs, and nothing once that is on', { tag: '@music-page' }, async ({ page }) => {
  await serve(page, { ...ALL, microphone: false });
  await page.goto('/');
  await page.getByTestId('start-button').click();
  const live = page.getByTestId('live-toggle');
  await expect(live).toBeEnabled();

  await page.getByTestId('capture-mode').selectOption('backend');
  await expect(live).toBeDisabled();
  await expect(live).toHaveAttribute('title', 'Off on this joe: JOE_ALLOW_MICROPHONE=1 turns it on');

  await page.getByTestId('capture-mode').selectOption('browser');
  await expect(live).toBeEnabled();
  await expect(live).not.toHaveClass(/is-off/);
  await expect(live).toHaveAttribute('title', '');
});

test('the hint numbers the steps it keeps again, and names each flag once', { tag: '@music-page' }, async ({ page }) => {
  await page.goto('/');
  const kept = await page.evaluate(async () => {
    const { adaptHint } = await import('/joe/components/Capabilities.js');
    const hint = document.createElement('div');
    hint.innerHTML = '<span class="hint-steps">'
      + '<span class="hint-step"><b>1.</b> a</span><span class="hint-sep">·</span>'
      + '<span class="hint-step" data-needs="microphone" data-what="b"><b>2.</b> b</span><span class="hint-sep">·</span>'
      + '<span class="hint-step" data-needs="microphone library" data-what="c"><b>3.</b> c</span><span class="hint-sep">·</span>'
      + '<span class="hint-step"><b>4.</b> d</span></span><span data-testid="hint-off" hidden></span>';
    adaptHint(hint, { off: (...names) => names.filter(n => n !== 'library') });
    return { steps: hint.querySelector('.hint-steps').textContent,
             said: hint.querySelector('[data-testid="hint-off"]').textContent };
  });

  expect(kept.steps).toBe('1. a·2. d');
  expect(kept.said).toBe('--allow microphone turns on b and c (docs/security.md)');
});
