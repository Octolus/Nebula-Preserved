import { randomBytes, scryptSync } from 'node:crypto';
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  openSync,
  closeSync,
  fsyncSync,
  renameSync,
  unlinkSync,
  lstatSync,
} from 'node:fs';
import { resolve, join } from 'node:path';
import { parseArgs } from 'node:util';
const { values } = parseArgs({
  options: {
    dir: { type: 'string' },
    owner: { type: 'string' },
    'password-stdin': { type: 'boolean' },
    'add-login': { type: 'boolean' },
    help: { type: 'boolean' },
  },
});
if (values.help) {
  console.log(
    'node scripts/bootstrap.mjs --dir <secrets-directory> --owner <operator-id> --password-stdin [--add-login]\nReads a password from stdin, creates secrets without printing them. --add-login adds a credential only; assign its role through the owner panel.',
  );
  process.exit(0);
}
if (
  !values.dir ||
  !values.owner ||
  !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(values.owner) ||
  !values['password-stdin']
)
  throw new Error(
    'Supply --dir, --owner (1–64 letters, digits, _, . or -; start with a letter/digit), and --password-stdin',
  );
let password = '';
for await (const chunk of process.stdin) {
  password += chunk;
  if (password.length > 1024) throw new Error('Password too long');
}
password = password.replace(/\r?\n$/, '');
if (password.length < 14) throw new Error('Use a password of at least 14 characters');
const dir = resolve(values.dir);
mkdirSync(dir, { recursive: true, mode: 0o700 });
const operatorPath = join(dir, 'admin-operators.json');
const salt = randomBytes(16).toString('hex');
const hash = `scrypt$16384$8$1$${salt}$${scryptSync(password, salt, 32).toString('hex')}`;
const lockPath = join(dir, 'admin-bootstrap.lock');
const lock = openSync(lockPath, 'wx', 0o600);
function replaceOperators(document) {
  const stat = lstatSync(operatorPath);
  if (!stat.isFile() || stat.nlink !== 1)
    throw new Error('Operator credentials must be a regular, unlinked file');
  const temporary = join(dir, `.operators-${randomBytes(16).toString('hex')}.tmp`);
  let fd;
  try {
    fd = openSync(temporary, 'wx', 0o600);
    writeFileSync(fd, JSON.stringify(document, null, 2) + '\n');
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    renameSync(temporary, operatorPath);
    if (process.platform === 'linux') {
      const directory = openSync(dir, 'r');
      try {
        fsyncSync(directory);
      } finally {
        closeSync(directory);
      }
    }
  } finally {
    if (fd !== undefined) closeSync(fd);
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}
try {
  if (values['add-login']) {
    const document = JSON.parse(readFileSync(operatorPath, 'utf8'));
    if (document.operators.some((o) => o.id === values.owner))
      throw new Error('Credential already exists; no file changed');
    document.operators.push({
      id: values.owner,
      role: 'moderator',
      enabled: true,
      password_scrypt: hash,
    });
    replaceOperators(document);
  } else {
    const files = ['admin-token.txt', 'panel-session-key.txt', 'admin-operators.json'];
    if (files.some((file) => existsSync(join(dir, file))))
      throw new Error('Secrets already exist; nothing overwritten');
    writeFileSync(join(dir, files[0]), randomBytes(48).toString('base64url') + '\n', {
      flag: 'wx',
      mode: 0o600,
    });
    writeFileSync(join(dir, files[1]), randomBytes(48).toString('base64url') + '\n', {
      flag: 'wx',
      mode: 0o600,
    });
    writeFileSync(
      operatorPath,
      JSON.stringify(
        { operators: [{ id: values.owner, role: 'owner', enabled: true, password_scrypt: hash }] },
        null,
        2,
      ) + '\n',
      { flag: 'wx', mode: 0o600 },
    );
  }
} finally {
  closeSync(lock);
  unlinkSync(lockPath);
}
console.log('Operator credential saved. No secret values were printed.');
