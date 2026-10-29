import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes, scryptSync, createHmac } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import {
  issue,
  verify,
  csrf,
  validCsrf,
  passwordMatches,
  authenticate,
  allowLogin,
  readJson,
  secret,
} from '../src/lib/security.ts';
const directory = mkdtempSync(join(tmpdir(), 'nebula-panel-test-'));
after(() => rmSync(directory, { recursive: true, force: true }));
const key = randomBytes(48).toString('hex');
writeFileSync(join(directory, 'key'), key);
process.env.NEBULA_PANEL_SESSION_KEY_FILE = join(directory, 'key');
process.env.NEBULA_PANEL_ORIGIN = 'http://localhost:4321';
test('signed sessions reject tampering, expiration and rotation', () => {
  const issued = issue('test-owner');
  assert.equal(verify(issued)?.id, 'test-owner');
  assert.equal(verify(issued + 'x'), null);
  assert.equal(verify('not.a.session'), null);
  const expired = Buffer.from(JSON.stringify({ id: 'test-owner', nonce: 'n', exp: 1 })).toString(
    'base64url',
  );
  assert.equal(
    verify(expired + '.' + createHmac('sha256', key).update(expired).digest('base64url')),
    null,
  );
  writeFileSync(join(directory, 'key'), randomBytes(48).toString('hex'));
  assert.equal(verify(issued), null);
  writeFileSync(join(directory, 'key'), key);
});
test('CSRF requires both exact origin and session-bound token', () => {
  const session = verify(issue('test-owner'))!,
    other = verify(issue('test-owner'))!;
  const request = (origin: string, token: string) =>
    new Request('http://localhost:4321/api/logout', {
      method: 'POST',
      headers: { origin, 'x-csrf-token': token },
    });
  assert.ok(validCsrf(request('http://localhost:4321', csrf(session)), session));
  assert.ok(!validCsrf(request('https://untrusted.invalid', csrf(session)), session));
  assert.ok(!validCsrf(request('http://localhost:4321', csrf(other)), session));
  assert.ok(!validCsrf(request('null', csrf(session)), session));
});
test('scrypt passwords require exact supported format and enabled operator', async () => {
  const password = randomBytes(24).toString('hex'),
    salt = randomBytes(16).toString('hex');
  const hash = `scrypt$16384$8$1$${salt}$${scryptSync(password, salt, 32).toString('hex')}`;
  assert.ok(await passwordMatches(password, hash));
  assert.ok(!(await passwordMatches(password + 'x', hash)));
  assert.ok(!(await passwordMatches(password, hash.replace('16384', '1073741824'))));
  const file = join(directory, 'operators.json');
  writeFileSync(
    file,
    JSON.stringify({
      operators: [
        { id: 'test-owner', enabled: true, password_scrypt: hash },
        { id: 'test-disabled', enabled: false, password_scrypt: hash },
      ],
    }),
  );
  process.env.NEBULA_ADMIN_OPERATORS_FILE = file;
  assert.ok(await authenticate('test-owner', password));
  assert.ok(!(await authenticate('test-disabled', password)));
  assert.ok(!(await authenticate('missing', password)));
});
test('missing secrets fail closed and login attempts are bounded', () => {
  assert.throws(() => secret('NEBULA_TEST_UNSET_SECRET'));
  for (let n = 0; n < 10; n++) assert.ok(allowLogin('synthetic-address'));
  assert.ok(!allowLogin('synthetic-address'));
});
test('JSON input rejects non-JSON and streaming oversized bodies', async () => {
  const req = (text: string, type = 'application/json') =>
    new Request('http://localhost', {
      method: 'POST',
      body: text,
      headers: { 'Content-Type': type },
    });
  assert.deepEqual(await readJson(req('{"ok":true}'), 100), { ok: true });
  await assert.rejects(readJson(req('x'.repeat(101)), 100));
  await assert.rejects(readJson(req('{}', 'text/plain'), 100));
});
test('bootstrap emits no secrets and refuses to overwrite existing credentials', () => {
  const output = join(directory, 'generated'),
    password = randomBytes(24).toString('hex');
  const args = [
    'scripts/bootstrap.mjs',
    '--dir',
    output,
    '--owner',
    'synthetic-owner',
    '--password-stdin',
  ];
  const first = spawnSync(process.execPath, args, { encoding: 'utf8', input: password });
  assert.equal(first.status, 0);
  assert.ok(!first.stdout.includes(password));
  const second = spawnSync(process.execPath, args, { encoding: 'utf8', input: password });
  assert.notEqual(second.status, 0);
  assert.ok(!second.stdout.includes(password));
});
test('concurrent credential additions never lose committed operators', async () => {
  const output = join(directory, 'concurrent'),
    password = randomBytes(24).toString('hex');
  const args = [
    'scripts/bootstrap.mjs',
    '--dir',
    output,
    '--owner',
    'first-owner',
    '--password-stdin',
  ];
  assert.equal(spawnSync(process.execPath, args, { input: password, encoding: 'utf8' }).status, 0);
  const before = readFileSync(join(output, 'admin-token.txt'), 'utf8');
  const results = await Promise.all(
    Array.from(
      { length: 6 },
      (_, i) =>
        new Promise<{ id: string; code: number | null }>((resolve) => {
          const id = 'operator-' + i;
          const child = spawn(
            process.execPath,
            [
              'scripts/bootstrap.mjs',
              '--dir',
              output,
              '--owner',
              id,
              '--password-stdin',
              '--add-login',
            ],
            { stdio: ['pipe', 'ignore', 'ignore'] },
          );
          child.stdin.end(password);
          child.on('exit', (code) => resolve({ id, code }));
        }),
    ),
  );
  const document = JSON.parse(readFileSync(join(output, 'admin-operators.json'), 'utf8'));
  assert.equal(document.operators.length, 1 + results.filter((r) => r.code === 0).length);
  assert.ok(document.operators.some((o: { id: string }) => o.id === 'first-owner'));
  for (const result of results.filter((r) => r.code === 0))
    assert.ok(document.operators.some((o: { id: string }) => o.id === result.id));
  assert.equal(readFileSync(join(output, 'admin-token.txt'), 'utf8'), before);
});
