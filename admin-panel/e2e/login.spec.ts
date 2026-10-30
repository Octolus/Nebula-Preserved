import { test, expect } from '@playwright/test';

test('unhydrated login cannot accept credentials and native fallback uses POST', async ({
  page,
}) => {
  await page.route('**/*', async (route) => {
    if (route.request().resourceType() === 'script') await route.abort();
    else await route.continue();
  });
  await page.goto('/login');
  await expect(page.getByLabel('Operator ID')).toBeDisabled();
  await expect(page.getByLabel('Password', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeDisabled();
  await expect(page.locator('form')).toHaveAttribute('method', 'post');
  await expect(page.locator('form')).toHaveAttribute('action', '/api/login');

  const submission = page.waitForRequest(
    (request) => new URL(request.url()).pathname === '/api/login',
  );
  await page.route('**/api/login', (route) =>
    route.fulfill({ status: 400, body: 'Synthetic fallback' }),
  );
  await page.locator('form').evaluate((form: HTMLFormElement) => {
    for (const input of form.querySelectorAll('input')) {
      input.disabled = false;
      input.value = 'synthetic-fallback-marker';
    }
    form.submit();
  });
  const request = await submission;
  expect(request.method()).toBe('POST');
  expect(new URL(request.url()).search).toBe('');
  expect(request.postData()).toContain('password=synthetic-fallback-marker');
});

test('hydrated login sends JSON credentials in POST body and displays authentication errors', async ({
  page,
}) => {
  await page.route('**/api/login', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { message: 'Synthetic authentication rejection' } }),
    }),
  );
  await page.goto('/login');
  await page.getByLabel('Operator ID').fill('synthetic-operator');
  await page.getByLabel('Password', { exact: true }).fill('synthetic-password-marker');
  const submission = page.waitForRequest(
    (request) => new URL(request.url()).pathname === '/api/login',
  );
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const request = await submission;
  expect(request.method()).toBe('POST');
  expect(new URL(request.url()).search).toBe('');
  expect(request.headers()['content-type']).toBe('application/json');
  expect(request.postDataJSON()).toEqual({
    id: 'synthetic-operator',
    password: 'synthetic-password-marker',
  });
  await expect(page.getByRole('alert')).toHaveText('Synthetic authentication rejection');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
});
