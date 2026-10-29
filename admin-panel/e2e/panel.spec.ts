import { test, expect, type Page, type Locator } from '@playwright/test';
async function choose(page: Page, control: Locator, label: string) {
  await control.click();
  await page.getByRole('option', { name: label, exact: true }).click();
}
import { readFileSync } from 'node:fs';
type Fixture = {
  fixture_only: boolean;
  account_id: string;
  offer_id: string;
  companion_id: string;
  report_id: string;
};
let fixture: Fixture, password: string;
test.beforeAll(() => {
  const file = process.env.NEBULA_E2E_FIXTURE_FILE,
    pw = process.env.NEBULA_E2E_PASSWORD_FILE;
  if (!file || !pw)
    throw new Error(
      'Explicit NEW synthetic fixture manifest and password files required. Never run against production.',
    );
  fixture = JSON.parse(readFileSync(file, 'utf8'));
  if (fixture.fixture_only !== true || fixture.account_id !== '76561190000000001')
    throw new Error('Synthetic fixture admission failed');
  password = readFileSync(pw, 'utf8').trim();
});
test('moderator can moderate players, cannot change credits, and revocation invalidates its session', async ({
  page,
  browser,
}) => {
  const passwordFile = process.env.NEBULA_E2E_MODERATOR_PASSWORD_FILE;
  if (!passwordFile) throw new Error('Explicit synthetic moderator password file required');
  const modPassword = readFileSync(passwordFile, 'utf8').trim();
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Panel access', exact: true }).click();
  const access = page.locator('form').filter({ has: page.getByLabel('Panel role') });
  await access.getByLabel('Operator ID').fill('synthetic-moderator');
  await access.getByLabel('Reason for this change').fill('Synthetic moderator access');
  await access.getByRole('checkbox').check();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/operators/synthetic-moderator') && r.request().method() === 'POST',
  );
  await access.getByRole('button', { name: 'Set panel access', exact: true }).click();
  expect((await created).status()).toBe(200);
  const context = await browser.newContext();
  const moderator = await context.newPage();
  try {
    await moderator.goto(new URL('/login', page.url()).href);
    await moderator.getByLabel('Operator ID').fill('synthetic-moderator');
    await moderator.getByLabel('Password', { exact: true }).fill(modPassword);
    await moderator.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(
      moderator.getByRole('heading', { name: 'Your community, connected.' }),
    ).toBeVisible();
    await expect(moderator.getByRole('button', { name: 'Panel access', exact: true })).toHaveCount(
      0,
    );
    await moderator.getByRole('button', { name: 'Players', exact: true }).click();
    await moderator
      .getByRole('row')
      .filter({ has: moderator.getByRole('cell', { name: fixture.account_id, exact: true }) })
      .getByRole('link', { name: 'Open', exact: true })
      .click();
    await expect(moderator.getByRole('heading', { name: 'Player account' })).toBeVisible();
    await moderator.getByRole('tab', { name: 'Moderation', exact: true }).click();
    await expect(moderator.getByLabel('Amount to add or deduct')).toHaveCount(0);
    const token = await moderator.locator('meta[name="csrf-token"]').getAttribute('content');
    const denied = await moderator.request.post(
      '/api/manage/users/' + fixture.account_id + '/wallet-adjustments',
      {
        headers: {
          Origin: new URL(page.url()).origin,
          'X-CSRF-Token': token!,
          'Idempotency-Key': 'synthetic-moderator-denial-0001',
        },
        data: { currency: 'crystals', delta: 500, reason: 'Denied moderator mutation' },
      },
    );
    expect(denied.status()).toBe(403);
    await expect(moderator.getByLabel('Display label (empty clears it)')).toHaveCount(0);
    for (const [index, [path, body]] of [
      [
        'users/' + fixture.account_id + '/staff-label',
        { label: 'Denied', reason: 'Denied moderator staff label' },
      ],
      ['moderation/maintenance', { minutes: 5, reason: 'Denied moderator maintenance' }],
      [
        'moderation/news',
        { text: 'Denied moderator news', expires_at: null, reason: 'Denied moderator news' },
      ],
      [
        'operators/synthetic-moderator/player-link',
        { account_id: fixture.account_id, reason: 'Denied moderator player link' },
      ],
    ].entries()) {
      const response = await moderator.request.post('/api/manage/' + path, {
        headers: {
          Origin: new URL(page.url()).origin,
          'X-CSRF-Token': token!,
          'Idempotency-Key': 'synthetic-moderator-denied-extra-' + index,
        },
        data: body,
      });
      expect(response.status()).toBe(403);
    }
    const moderation = moderator
      .locator('form')
      .filter({ has: moderator.getByLabel('Moderation action') });
    for (const action of ['mute', 'unmute']) {
      await choose(
        moderator,
        moderation.getByLabel('Moderation action'),
        action === 'mute' ? 'Mute player' : 'Unmute player',
      );
      await moderation.getByLabel('Moderation reason').fill('Synthetic moderator ' + action);
      await moderation.getByRole('checkbox').check();
      const committed = moderator.waitForResponse(
        (response) =>
          response.url().endsWith('/' + action) && response.request().method() === 'POST',
      );
      await moderation
        .getByRole('button', {
          name: action === 'mute' ? 'Mute player' : 'Unmute player',
          exact: true,
        })
        .click();
      expect((await committed).status()).toBe(200);
      await expect(
        moderator.getByRole('status').filter({ hasText: 'Moderation policy committed' }),
      ).toBeVisible();
      await expect(moderation.getByRole('checkbox')).not.toBeChecked();
    }
    await moderator.getByRole('button', { name: 'Moderation', exact: true }).click();
    await moderator.getByRole('tab', { name: 'Login news', exact: true }).click();
    await expect(moderator.getByRole('heading', { name: 'Login news', exact: true })).toBeVisible();
    await expect(moderator.getByLabel('Maintenance minutes', { exact: true })).toHaveCount(0);
    await expect(moderator.getByLabel('News text', { exact: true })).toHaveCount(0);
    await access.getByLabel('Operator ID').fill('synthetic-moderator');
    await choose(page, access.getByLabel('Access', { exact: true }), 'disabled');
    await access.getByLabel('Reason for this change').fill('Synthetic access revocation');
    await access.getByRole('checkbox').check();
    const disabled = page.waitForResponse(
      (r) => r.url().endsWith('/operators/synthetic-moderator') && r.request().method() === 'POST',
    );
    await access.getByRole('button', { name: 'Set panel access', exact: true }).click();
    expect((await disabled).status()).toBe(200);
    expect((await moderator.request.get('/api/manage/stats')).status()).toBe(401);
    await moderator.goto(new URL('/', page.url()).href);
    await expect(moderator).toHaveURL(/\/login$/);
  } finally {
    await context.close();
  }
});

test('owner maintenance, report review, display labels and login news use separate controls', async ({
  page,
}) => {
  test.slow();
  expect(fixture.report_id).toMatch(/^[a-f0-9]{64}$/);
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Moderation', exact: true }).click();
  await page.getByRole('tab', { name: 'Maintenance', exact: true }).click();
  const maintenance = page
    .locator('form')
    .filter({ has: page.getByLabel('Maintenance minutes', { exact: true }) });
  for (const minutes of ['5', '0']) {
    await maintenance.getByLabel('Maintenance minutes', { exact: true }).fill(minutes);
    await maintenance.getByLabel('Maintenance reason').fill('Synthetic maintenance ' + minutes);
    await maintenance.getByRole('checkbox').check();
    const committed = page.waitForResponse(
      (response) =>
        response.url().endsWith('/moderation/maintenance') &&
        response.request().method() === 'POST',
    );
    await maintenance.getByRole('button', { name: 'Set maintenance notice', exact: true }).click();
    expect((await committed).status()).toBe(200);
    await expect(page.getByText('Reported maintenance notice:', { exact: false })).toContainText(
      minutes + ' minutes',
    );
  }
  await page.getByRole('tab', { name: 'Reports & history', exact: true }).click();
  const row = page
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: fixture.report_id, exact: true }) });
  await row.getByRole('button', { name: 'Review', exact: true }).click();
  const review = page.locator('form').filter({ has: page.getByLabel('Report status') });
  await expect(
    review.getByText('The reported username is not an account ID.', { exact: false }),
  ).toBeVisible();
  await choose(page, review.getByLabel('Report status'), 'resolved');
  await review.getByLabel('Operator note (optional)').fill('Synthetic review note');
  await review.getByLabel('Report review reason').fill('Synthetic report review complete');
  await review.getByRole('checkbox').check();
  const reviewed = page.waitForResponse(
    (response) =>
      response.url().endsWith('/moderation/reports/' + fixture.report_id) &&
      response.request().method() === 'POST',
  );
  await review.getByRole('button', { name: 'Save report review', exact: true }).click();
  expect((await reviewed).status()).toBe(200);
  await expect(row.getByRole('cell', { name: 'resolved', exact: true })).toBeVisible();
  await review.getByRole('button', { name: 'Close review', exact: true }).click();
  await page.getByRole('button', { name: 'Moderation history', exact: true }).click();
  await expect(
    page.getByRole('cell', { name: 'Synthetic report review complete', exact: true }),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'Player actions', exact: true }).click();
  await page.getByLabel('Player account ID').fill(fixture.account_id);
  await page.getByRole('button', { name: 'Look up player', exact: true }).click();
  const labelForm = page
    .locator('form')
    .filter({ has: page.getByLabel('Display label (empty clears it)') });
  for (const label of ['[FIXTURE] Helper', '']) {
    await labelForm.getByLabel('Display label (empty clears it)').fill(label);
    await labelForm.getByLabel('Display label reason').fill('Synthetic display label update');
    await labelForm.getByRole('checkbox').check();
    const committed = page.waitForResponse(
      (response) =>
        response.url().endsWith('/staff-label') && response.request().method() === 'POST',
    );
    await labelForm.getByRole('button', { name: 'Set display label', exact: true }).click();
    expect((await committed).status()).toBe(200);
    await expect(labelForm.getByRole('checkbox')).not.toBeChecked();
  }
  await page.getByRole('tab', { name: 'Login news', exact: true }).click();
  const publish = page
    .locator('form')
    .filter({ has: page.getByLabel('News text', { exact: true }) });
  await publish.getByLabel('News text', { exact: true }).fill('Synthetic preservation login news');
  await publish.getByLabel('News publication reason').fill('Synthetic news publication');
  await publish.getByRole('checkbox').check();
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/moderation/news') && response.request().method() === 'POST',
  );
  await publish.getByRole('button', { name: 'Publish news', exact: true }).click();
  const published = await created;
  expect(published.status()).toBe(200);
  const newsId = (await published.json()).data.after.news_id;
  expect(newsId).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/);
  const newsRow = page
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: newsId, exact: true }) });
  await newsRow.getByRole('button', { name: 'Archive', exact: true }).click();
  const archive = page.locator('form').filter({ has: page.getByLabel('News archive reason') });
  await archive.getByLabel('News archive reason').fill('Synthetic news archive');
  await archive.getByRole('checkbox').check();
  const archived = page.waitForResponse(
    (response) =>
      response.url().endsWith('/moderation/news/' + newsId + '/archive') &&
      response.request().method() === 'POST',
  );
  await archive.getByRole('button', { name: 'Confirm archive', exact: true }).click();
  expect((await archived).status()).toBe(200);
  await expect(newsRow.getByText('Inactive', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Game role', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Panel access', exact: true }).click();
  const link = page.locator('form').filter({ has: page.getByLabel('Operator to link') });
  for (const accountId of [fixture.account_id, '']) {
    await link.getByLabel('Operator to link').fill('synthetic-moderator');
    await link.getByLabel('Player account ID (empty unlinks)').fill(accountId);
    await link.getByLabel('Reason for this change').fill('Synthetic explicit player link');
    await link.getByRole('checkbox').check();
    const committed = page.waitForResponse(
      (response) =>
        response.url().endsWith('/operators/synthetic-moderator/player-link') &&
        response.request().method() === 'POST',
    );
    await link.getByRole('button', { name: 'Link operator to player', exact: true }).click();
    const result = await committed;
    expect(result.status()).toBe(200);
    expect((await result.json()).data.after.account_id).toBe(accountId || null);
    await expect(link.getByRole('checkbox')).not.toBeChecked();
  }
});

test('moderation lookup commits bounded policies and preserves idempotent replay and CSRF checks', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Moderation', exact: true }).click();
  await page.getByRole('tab', { name: 'Player actions', exact: true }).click();
  await page.getByLabel('Player account ID').fill(fixture.account_id);
  await page.getByRole('button', { name: 'Look up player', exact: true }).click();
  const form = page.locator('form').filter({ has: page.getByLabel('Moderation action') });
  for (const [action, label, state] of [
    ['ban', 'Ban player', 'Banned'],
    ['unban', 'Unban player', 'Not banned'],
    ['mute', 'Mute player', 'Muted'],
    ['unmute', 'Unmute player', 'Not muted'],
    ['kick', 'Kick player', 'Not banned'],
  ]) {
    await choose(page, form.getByLabel('Moderation action'), label);
    await form.getByLabel('Moderation reason').fill('Synthetic moderation ' + action);
    await expect(form.getByRole('button', { name: label, exact: true })).toBeDisabled();
    await form.getByRole('checkbox').check();
    const committed = page.waitForResponse(
      (response) => response.url().endsWith('/' + action) && response.request().method() === 'POST',
    );
    await form.getByRole('button', { name: label, exact: true }).click();
    const response = await committed;
    expect(response.status()).toBe(200);
    await expect(page.getByText(state, { exact: true })).toBeVisible();
    const original = response.request();
    const replay = await page.request.post(new URL(original.url()).pathname, {
      headers: await original.allHeaders(),
      data: original.postData()!,
    });
    expect(replay.status()).toBe(200);
    expect((await replay.json()).data.replayed).toBe(true);
    const denied = await page.request.post(new URL(original.url()).pathname, {
      headers: {
        Origin: new URL(page.url()).origin,
        'Idempotency-Key': 'synthetic-denied-moderation-0001',
      },
      data: { reason: 'Denied moderation CSRF' },
    });
    expect(denied.status()).toBe(403);
    await expect(form.getByRole('checkbox')).not.toBeChecked();
  }
  await expect(page.getByLabel('Game role')).toHaveCount(0);
});
test('operator UI, live mutations, audit, replay and CSRF protections', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your community, connected.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Server support' })).toBeVisible();
  await page.screenshot({ path: 'test-results/overview-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Players', exact: true }).click();
  await page.getByLabel('Search records').fill('PreservationDemo');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: fixture.account_id, exact: true }) })
    .getByRole('link', { name: 'Open', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'Player account' })).toBeVisible();
  await page.getByRole('tab', { name: 'Credits', exact: true }).click();
  const wallet = page.locator('form').filter({ has: page.getByLabel('Amount to add or deduct') });
  await wallet.getByLabel('Amount to add or deduct').fill('17');
  await wallet.getByLabel('Reason for this change').fill('Synthetic integration adjustment');
  await wallet.getByRole('checkbox').check();
  const walletResponse = page.waitForResponse(
    (r) => r.url().endsWith('/wallet-adjustments') && r.request().method() === 'POST',
  );
  await wallet.getByRole('button', { name: 'Adjust credits', exact: true }).click();
  const adjusted = await walletResponse;
  expect(adjusted.status()).toBe(200);
  const adjustedBody = await adjusted.json();
  expect(adjustedBody.data.after.crystals).toBe(117);
  const request = adjusted.request();
  const headers = await request.allHeaders();
  const replay = await page.request.post(new URL(request.url()).pathname, {
    headers,
    data: request.postData()!,
  });
  expect(replay.status()).toBe(200);
  expect((await replay.json()).data.replayed).toBe(true);
  const unprotected = await page.request.post(new URL(request.url()).pathname, {
    data: { currency: 'crystals', delta: 17, reason: 'Denied CSRF' },
    headers: {
      Origin: new URL(request.url()).origin,
      'Idempotency-Key': 'synthetic-denied-csrf-0001',
    },
  });
  expect(unprotected.status()).toBe(403);
  const forged = await page.request.post(new URL(request.url()).pathname, {
    data: request.postData()!,
    headers: { ...headers, origin: 'https://untrusted.invalid' },
  });
  expect(forged.status()).toBe(403);
  await page.getByRole('tab', { name: 'Inventory', exact: true }).click();
  const grant = page.locator('form').filter({ has: page.getByLabel('Item or offer ID') });
  await grant.getByLabel('Item or offer ID').fill(fixture.offer_id);
  await grant.getByLabel('Reason for this change').fill('Synthetic integration item grant');
  await grant.getByRole('checkbox').check();
  const grantResponse = page.waitForResponse(
    (r) => r.url().endsWith('/items') && r.request().method() === 'POST',
  );
  await grant.getByRole('button', { name: 'Grant item', exact: true }).click();
  expect((await grantResponse).status()).toBe(200);
  await expect(
    page
      .locator('[data-slot="card"]')
      .filter({ has: page.getByRole('heading', { name: 'Owned items', exact: false }) })
      .getByRole('cell', { name: fixture.companion_id, exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: 'test-results/player-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Audit log', exact: true }).click();
  await expect(
    page.getByRole('cell', { name: 'Synthetic integration adjustment', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('cell', { name: 'Synthetic integration item grant', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Credit adjustments', exact: true }).click();
  await expect(
    page.getByRole('cell', { name: 'Synthetic integration adjustment', exact: true }),
  ).toHaveCount(1);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: 'test-results/ledger-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(errors).toEqual([]);
  const denied = await page.request.get('/api/manage/stats');
  expect(denied.status()).toBe(401);
});
