import { constants } from 'node:fs';
import { lstat, open, realpath } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';

export const maximumPreviewBytes = 1024 * 1024;

// Keys refer only to extracted WebP files. Never accept resource paths or URLs
// from a browser, and never fetch the retired game's thumbnail hosts.
export async function catalogPreview(key: string, directory?: string) {
  if (!/^[a-f0-9]{64}$/.test(key) || !directory) return null;
  let file;
  try {
    const root = resolve(directory);
    if ((await realpath(root)) !== root || !(await lstat(root)).isDirectory()) return null;
    const path = join(root, key + '.webp');
    const metadata = await lstat(path);
    if (!metadata.isFile() || metadata.isSymbolicLink()) return null;
    file = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    const stat = await file.stat();
    if (!stat.isFile() || stat.size < 12 || stat.size > maximumPreviewBytes) return null;
    // Read a fixed maximum even if a local operator replaces or grows a file.
    const data = Buffer.alloc(stat.size + 1);
    let length = 0;
    while (length < data.length) {
      const read = await file.read(data, length, data.length - length, null);
      if (!read.bytesRead) break;
      length += read.bytesRead;
    }
    if (length !== stat.size) return null;
    const bytes = data.subarray(0, length);
    if (bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WEBP')
      return null;
    if (bytes.readUInt32LE(4) + 8 !== bytes.length) return null;
    return { bytes, etag: '"' + createHash('sha256').update(bytes).digest('hex') + '"' };
  } catch {
    return null;
  } finally {
    await file?.close();
  }
}
