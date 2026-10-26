const { test, expect } = require('@playwright/test');

// The windows by key: L the Library, A the Results, Esc closes them; T is the
// transcript pane's own (transcript-pane.spec.js).

test('L opens and closes the Library, and A the analysis Results', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  const library = page.getByTestId('capture-panel');

  await page.keyboard.press('l');
  await expect(library).toBeVisible();
  await page.keyboard.press('l');
  await expect(library).toBeHidden();

  await page.keyboard.press('a');
  await expect(page.getByTestId('results-panel')).toBeVisible();
  await page.keyboard.press('a');
  await expect(page.getByTestId('results-panel')).toBeHidden();
});

test('Esc closes whatever is open, and opens nothing that was closed', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.keyboard.press('l');
  await page.keyboard.press('t');
  await expect(page.getByTestId('transcript-pane')).toBeVisible();

  await page.keyboard.press('Escape');

  await expect(page.locator('#paneltab-library')).toHaveCount(0);
  await expect(page.locator('#paneltab-transcript')).toHaveCount(0);
  // The Results were never open, and closing what was does not open them.
  for (let i = 0; i < 6; i++) {
    await expect(page.locator('#paneltab-results')).toHaveCount(0);
    await page.waitForTimeout(50);
  }
});

test('R still asks the voice loop to say it again, and opens neither the Library nor the Results', async ({ page }) => {
  const answers = [];
  await page.route(url => url.pathname === '/api/voice/answer', route => {
    answers.push(route.request().postDataJSON());
    route.fulfill({ json: { ok: true } });
  });
  await page.goto('/');
  await page.waitForSelector('canvas');

  await page.keyboard.press('r');

  await expect.poll(() => answers).toEqual([{ text: 'repeat' }]);
  await expect(page.locator('#paneltab-results')).toHaveCount(0);
  await expect(page.locator('#paneltab-library')).toHaveCount(0);
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

  await expect(page.getByTestId('capture-panel')).toBeHidden();
  await expect(page.getByTestId('results-panel')).toBeHidden();
});
