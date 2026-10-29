import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('mobile player tabs, deep links, catalog selection and related history stay usable', async ({
  page,
}) => {
  const file = process.env.NEBULA_E2E_FIXTURE_FILE,
    passwordFile = process.env.NEBULA_E2E_PASSWORD_FILE;
  if (!file || !passwordFile)
    throw new Error('Explicit disposable fixture and password files required.');
  const fixture = JSON.parse(readFileSync(file, 'utf8'));
  if (fixture.fixture_only !== true || typeof fixture.account_id !== 'string')
    throw new Error('Disposable fixture required.');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page
    .getByLabel('Password', { exact: true })
    .fill(readFileSync(passwordFile, 'utf8').trim());
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your community, connected.' })).toBeVisible();
  await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click();
  await page.getByRole('button', { name: 'Players', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByLabel('Search records').fill('PreservationDemo');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('link', { name: fixture.account_id, exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Summary', exact: true })).toHaveAttribute(
    'data-state',
    'active',
  );
  await expect(page.getByText('Last login', { exact: true })).toBeVisible();
  for (const tab of ['Inventory', 'Purchases', 'Credits', 'Moderation', 'Activity', 'Summary']) {
    await page.getByRole('tab', { name: tab, exact: true }).click();
    await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute(
      'data-state',
      'active',
    );
    await expect
      .poll(() =>
        page.evaluate(() => {
          const list = document
            .querySelector('[aria-label="Player sections"]')!
            .getBoundingClientRect();
          const content = document
            .querySelector('[data-slot="tabs-content"][data-state="active"]')!
            .getBoundingClientRect();
          return (
            content.top >= list.bottom &&
            [...document.querySelectorAll('[role="tab"]')].every((tab) => {
              const box = tab.getBoundingClientRect();
              return box.height >= 44 && box.bottom <= list.bottom;
            })
          );
        }),
      )
      .toBe(true);
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
  }
  await page.getByRole('tab', { name: 'Inventory', exact: true }).click();
  await page.getByLabel('Find catalog items').fill(fixture.offer_id);
  await page.getByRole('button', { name: 'Search catalog', exact: true }).click();
  await page.getByRole('button', { name: 'Choose item', exact: true }).click();
  await expect(page.getByLabel('Item or offer ID')).toHaveValue(fixture.offer_id);
  await expect(page.getByRole('button', { name: 'Grant item', exact: true })).toBeDisabled();
  await page.getByRole('tab', { name: 'Credits', exact: true }).click();
  const form = page.locator('form').filter({ has: page.getByLabel('Amount to add or deduct') });
  await form.getByLabel('Currency', { exact: true }).click();
  await page.getByRole('option', { name: 'Nebula Points', exact: true }).click();
  await form.getByLabel('Amount to add or deduct').fill('1');
  await form.getByLabel('Reason for this change').fill('Synthetic mobile adjustment');
  await form.getByRole('checkbox').check();
  // Editing a confirmed amount must require confirmation again.
  await form.getByLabel('Amount to add or deduct').fill('2');
  await expect(form.getByRole('checkbox')).not.toBeChecked();
  await form.getByRole('checkbox').check();
  const committed = page.waitForResponse(
    (response) =>
      response.url().endsWith('/wallet-adjustments') && response.request().method() === 'POST',
  );
  await form.getByRole('button', { name: 'Adjust credits', exact: true }).click();
  expect((await committed).status()).toBe(200);
  await expect(
    page.getByRole('definition').filter({ hasText: 'Synthetic mobile adjustment' }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Credits', exact: true })).toHaveAttribute(
    'data-state',
    'active',
  );
  await expect(
    page.getByRole('definition').filter({ hasText: 'Synthetic mobile adjustment' }),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'Activity', exact: true }).click();
  await expect(
    page.getByRole('definition').filter({ hasText: 'Synthetic mobile adjustment' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Before / after' }).first().click();
  for (const width of [320, 375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: 'test-results/player-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 320, height: 812 });
  for (const [view, title] of [
    ['overview', 'Overview'],
    ['users', 'Players'],
    ['catalog', 'Item catalog'],
    ['transactions', 'Credit adjustments'],
    ['audit', 'Audit log'],
    ['operators', 'Panel access'],
    ['moderation', 'Moderation'],
  ]) {
    await page.goto('/#' + view);
    await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible();
    await expect(page.getByText('Loading server records�', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
  }
  for (const title of ['Reports & history', 'Maintenance', 'Login news', 'Player actions']) {
    await page.getByRole('tab', { name: title, exact: true }).click();
    await expect(page.getByRole('tab', { name: title, exact: true })).toHaveAttribute(
      'data-state',
      'active',
    );
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
  }
  expect(errors).toEqual([]);
});
