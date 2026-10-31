const { test, expect } = require('@playwright/test');

// The side panels by key: L the Library, A the Results, Esc closes them; T is
// the transcript pane's own (transcript-pane.spec.js).

async function onScreen(page, testid) {
  const box = await page.getByTestId(testid).boundingBox();
  return box.x < (await page.evaluate(() => window.innerWidth)) - 1;
}

test('L opens and closes the Library, and A the analysis Results', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  const library = page.getByTestId('capture-panel');

  await page.keyboard.press('l');
  await expect(library).toHaveClass(/open/);
  await page.keyboard.press('l');
  await expect(library).not.toHaveClass(/open/);

  await page.keyboard.press('a');
  await expect.poll(() => onScreen(page, 'results-panel')).toBe(true);
  await page.keyboard.press('a');
  await expect.poll(() => onScreen(page, 'results-panel')).toBe(false);
});

test('Esc closes whatever is open, and nothing that was closed moves', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.keyboard.press('l');
  await page.keyboard.press('t');
  await expect(page.getByTestId('transcript-pane')).toBeVisible();

  await page.keyboard.press('Escape');

  await expect(page.getByTestId('capture-panel')).not.toHaveClass(/open/);
  await expect(page.getByTestId('transcript-pane')).toBeHidden();
  // The Results were never open: they do not slide across the window on the way out.
  for (let i = 0; i < 6; i++) {
    expect(await onScreen(page, 'results-panel')).toBe(false);
    await page.waitForTimeout(50);
  }
});

test('R still asks the voice loop to say it again, and opens nothing', async ({ page }) => {
  const answers = [];
  await page.route(url => url.pathname === '/api/voice/answer', route => {
    answers.push(route.request().postDataJSON());
    route.fulfill({ json: { ok: true } });
  });
  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.keyboard.press('r');

  await expect.poll(() => answers).toEqual([{ text: 'repeat' }]);
  expect(await onScreen(page, 'results-panel')).toBe(false);
  await expect(page.getByTestId('capture-panel')).not.toHaveClass(/open/);
});

test('keys typed into a field open nothing', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'typed';
    document.body.append(field);
  });

  await page.locator('#typed').fill('');
  await page.locator('#typed').pressSequentially('la');

  await expect(page.getByTestId('capture-panel')).not.toHaveClass(/open/);
  expect(await onScreen(page, 'results-panel')).toBe(false);
});
