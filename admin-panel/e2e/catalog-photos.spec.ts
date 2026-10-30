import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('catalog cards show readable labels, live currency alternatives, previews and graceful failures', async ({
  page,
}) => {
  const fixtureFile = process.env.NEBULA_E2E_FIXTURE_FILE,
    passwordFile = process.env.NEBULA_E2E_PASSWORD_FILE;
  if (
    !fixtureFile ||
    !passwordFile ||
    JSON.parse(readFileSync(fixtureFile, 'utf8')).fixture_only !== true
  )
    throw new Error('Explicit disposable fixture required');
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-owner');
  await page
    .getByLabel('Password', { exact: true })
    .fill(readFileSync(passwordFile, 'utf8').trim());
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your community, connected.' })).toBeVisible();
  const common = {
    kind: 'wardrobe',
    gender: 'FEMALE',
    category_label: 'Hat',
    name: 'Preserved wardrobe item',
    grantable: true,
    offers: [
      {
        offer_id: 'fixture-offer',
        shop_id: 'fixture-shop',
        shop_name: 'Fixture clothing',
        active: true,
        store_active: true,
        crystals: 25,
        np: 10,
      },
    ],
  };
  await page.route('**/api/manage/catalog?*', (route) =>
    route.fulfill({
      json: {
        data: {
          items: [
            { ...common, item_id: 'fixture-good', preview_url: '/api/catalog-preview/good' },
            { ...common, item_id: 'fixture-missing', preview_url: '/api/catalog-preview/missing' },
            { ...common, item_id: 'fixture-unlisted', offers: [] },
          ],
          total: 3,
          next_cursor: null,
          counts: { all: 3 },
          filters: {},
        },
      },
    }),
  );
  await page.route('**/api/catalog-preview/good', (route) =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" fill="teal"/></svg>',
    }),
  );
  await page.route('**/api/catalog-preview/missing', (route) => route.fulfill({ status: 404 }));
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/#catalog');
    await expect(page.getByLabel('Catalog item cards')).toBeVisible();
    await expect(page.getByText('Female Hat · fixture-', { exact: true })).toHaveCount(3);
    await expect(page.getByText('25 crystals / 10 Nebula Points', { exact: true })).toHaveCount(2);
    await expect(page.getByText('Not currently for sale', { exact: true })).toBeVisible();
    await expect(page.getByText('Preview could not load', { exact: true })).toBeVisible();
    await expect
      .poll(() =>
        page
          .locator('img')
          .first()
          .evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0),
      )
      .toBe(true);
    await expect(page.getByText('Preview not recovered', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.getByRole('button', { name: 'Compact list', exact: true }).click();
    await expect(page.getByLabel('Catalog item cards')).toHaveCount(0);
    await page
      .getByRole('button', { name: /^Inspect / })
      .first()
      .click();
    await expect(page.getByRole('dialog').getByText('fixture-good', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Cards', exact: true }).click();
    if (process.env.NEBULA_E2E_SCREENSHOT_DIR)
      await page.screenshot({
        path: process.env.NEBULA_E2E_SCREENSHOT_DIR + `/cards-${width}.png`,
        fullPage: true,
      });
  }
});
