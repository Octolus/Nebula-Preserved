import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, mkdir, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { catalogPreview, maximumPreviewBytes } from '../src/lib/catalog-preview.ts';

const key = 'a'.repeat(64);
// Minimal bounded WebP envelope; decoding actual pixels is verified separately
// against the extracted pack and browser, not inferred from this fixture.
const webp = Buffer.from('524946460c000000574542505650384c00000000', 'hex');

test('preview returns exact bounded WebP bytes and a content digest', async () => {
  const root = await mkdtemp(join(tmpdir(), 'nebula-preview-'));
  try {
    await writeFile(join(root, key + '.webp'), webp);
    const image = await catalogPreview(key, root);
    assert.ok(image);
    assert.deepEqual(image.bytes, webp);
    assert.match(image.etag, /^"[a-f0-9]{64}"$/);
    assert.equal((await catalogPreview(key, root))?.etag, image.etag);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('preview rejects paths, URLs, missing files, directories and unsafe content', async () => {
  const root = await mkdtemp(join(tmpdir(), 'nebula-preview-'));
  try {
    for (const bad of [
      '',
      '../secret',
      key + '.webp',
      key.toUpperCase(),
      'https://example.invalid',
    ])
      assert.equal(await catalogPreview(bad, root), null);
    assert.equal(await catalogPreview(key), null);
    assert.equal(await catalogPreview(key, root), null);
    await mkdir(join(root, key + '.webp'));
    assert.equal(await catalogPreview(key, root), null);
    await rm(join(root, key + '.webp'), { recursive: true });
    for (const data of [
      Buffer.alloc(0),
      Buffer.from('<svg>untrusted</svg>'),
      Buffer.alloc(maximumPreviewBytes + 1),
    ]) {
      await writeFile(join(root, key + '.webp'), data);
      assert.equal(await catalogPreview(key, root), null);
    }
    const corrupt = Buffer.from(webp);
    corrupt.writeUInt32LE(1, 4);
    await writeFile(join(root, key + '.webp'), corrupt);
    assert.equal(await catalogPreview(key, root), null);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('preview refuses a linked file on platforms permitting file symlinks', async (context) => {
  const root = await mkdtemp(join(tmpdir(), 'nebula-preview-'));
  try {
    await writeFile(join(root, 'outside.webp'), webp);
    try {
      await symlink(join(root, 'outside.webp'), join(root, key + '.webp'));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EPERM') {
        context.skip('Windows does not permit this process to create file symlinks');
        return;
      }
      throw error;
    }
    assert.equal(await catalogPreview(key, root), null);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
