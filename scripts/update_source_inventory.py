"""Check or explicitly refresh the Git-visible, source-only SHA256 inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = 'SOURCE-INVENTORY.json'


def visible_files(root: Path) -> list[str]:
    actual = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root,
                            check=True, capture_output=True, text=True).stdout.strip()
    if Path(actual).resolve() != root.resolve():
        raise ValueError('Run only inside this repository, not a surrounding Git worktree')
    result = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                            cwd=root, check=True, capture_output=True).stdout
    names = sorted({value.decode('utf-8') for value in result.split(b'\0') if value})
    return [name for name in names if name != INVENTORY]


def collect(root: Path, *, owned_temporary: str | None = None) -> dict:
    files = {}
    folded = set()
    for name in visible_files(root):
        if name == owned_temporary:
            continue
        parts = name.split('/')
        if (not parts or any(part in ('', '.', '..') for part in parts) or
                '\\' in name or ':' in name or name.casefold() in folded):
            raise ValueError('Unsafe or case-colliding source path')
        folded.add(name.casefold())
        path = root/name
        for ancestor in (path, *path.parents):
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked source paths cannot be inventoried')
            if ancestor == root:
                break
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Only regular source files can be inventoried')
        data = path.read_bytes()
        after = path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ValueError('Source changed during inventory')
        files[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    return files


def refresh(root: Path, *, write: bool) -> dict:
    path = root/INVENTORY
    original = path.read_bytes()
    value = json.loads(original)
    files = collect(root)
    count = len(files)
    total = sum(row['size'] for row in files.values())
    valid = (value.get('files') == files and value.get('file_count_excluding_inventory') == count
             and value.get('bytes_excluding_inventory') == total)
    if not write:
        if not valid:
            raise ValueError('Source inventory is stale; review changes, then run scripts/update_source_inventory.py --write')
        return {'files': count+1, 'inventory_current': True}
    value.update(files=files, file_count_excluding_inventory=count, bytes_excluding_inventory=total)
    raw = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode('utf-8')
    # Preserve curation/acceptance metadata. This does not make new runtime claims.
    descriptor, temporary = tempfile.mkstemp(prefix='.source-inventory-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original or collect(root, owned_temporary=Path(temporary).name) != files:
            raise ValueError('Concurrent source/inventory change; nothing replaced')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'files': count+1, 'inventory_current': True, 'runtime_validation_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(refresh(ROOT, write=args.write)))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
