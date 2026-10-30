"""Validate and atomically install an optional private, flat WebP preview pack."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import uuid

HEX = re.compile(r'[0-9a-f]{64}')
MAX_IMAGES = 15000
MAX_IMAGE = 1024 * 1024
MAX_INDEX = 32 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    path = Path(path).absolute()
    require(all(not p.is_symlink() for p in (path, *path.parents)), 'Linked preview path refused')
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'Preview input must be regular')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate preview JSON field')
        result[key] = value
    return result


def dimensions(data):
    require(len(data) >= 20 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'
            and int.from_bytes(data[4:8], 'little') == len(data) - 8, 'Invalid WebP container')
    offset = 12
    size = None
    image = False
    while offset + 8 <= len(data):
        tag = data[offset:offset + 4]
        length = int.from_bytes(data[offset + 4:offset + 8], 'little')
        start = offset + 8
        require(start + length <= len(data), 'Truncated WebP chunk')
        chunk = data[start:start + length]
        current = None
        if tag == b'VP8X':
            require(length == 10 and not (chunk[0] & 2), 'Invalid or animated WebP preview')
            current = (1 + int.from_bytes(chunk[4:7], 'little'), 1 + int.from_bytes(chunk[7:10], 'little'))
        elif tag == b'VP8L':
            require(length >= 5 and chunk[0] == 0x2f, 'Invalid lossless WebP header')
            bits = int.from_bytes(chunk[1:5], 'little')
            require(bits >> 29 == 0, 'Invalid WebP version')
            current = (1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff))
            image = True
        elif tag == b'VP8 ':
            require(length >= 10 and chunk[3:6] == b'\x9d\x01\x2a', 'Invalid lossy WebP header')
            current = (int.from_bytes(chunk[6:8], 'little') & 0x3fff,
                       int.from_bytes(chunk[8:10], 'little') & 0x3fff)
            image = True
        require(tag not in (b'ANIM', b'ANMF'), 'Animated previews refused')
        if current:
            require(size is None or size == current, 'Conflicting WebP dimensions')
            size = current
        offset = start + length + (length & 1)
    require(offset == len(data) and image and size and all(0 < n <= 16384 for n in size),
            'Invalid WebP preview dimensions')
    return size


def validate(archive, expected_sha256):
    archive = regular(archive)
    require(isinstance(expected_sha256, str) and HEX.fullmatch(expected_sha256), 'Invalid preview archive hash')
    require(archive.stat().st_size <= MAX_TOTAL + 32 * 1024 * 1024, 'Preview archive too large')
    sha = hashlib.sha256()
    with archive.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    require(sha.hexdigest() == expected_sha256, 'Preview archive hash mismatch')
    members = {}
    total = 0
    with tarfile.open(archive, 'r:') as source:
        for member in source:
            name = member.name
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not member.issparse()
                    and (name == 'index.json' or re.fullmatch(r'[0-9a-f]{64}\.webp', name)),
                    'Unsafe preview archive member')
            require(name not in members and len(members) <= MAX_IMAGES, 'Duplicate or excessive preview members')
            limit = MAX_INDEX if name == 'index.json' else MAX_IMAGE
            require(0 < member.size <= limit, 'Preview member exceeds size limit')
            total += member.size
            require(total <= MAX_TOTAL, 'Preview pack exceeds total limit')
            members[name] = member
        require('index.json' in members, 'Preview index missing')
        raw = source.extractfile(members['index.json']).read()
        index = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        require(isinstance(index, dict) and type(index.get('format_version')) is int
                and index['format_version'] == 1 and isinstance(index.get('entries'), list)
                and len(index['entries']) <= MAX_IMAGES, 'Invalid preview index schema')
        entries = {}
        for entry in index['entries']:
            require(isinstance(entry, dict) and isinstance(entry.get('key'), str)
                    and HEX.fullmatch(entry['key']), 'Invalid preview key')
            name = entry['key'] + '.webp'
            require(entry.get('filename') == name and name not in entries and name in members,
                    'Preview index inventory mismatch')
            require(isinstance(entry.get('sha256'), str) and HEX.fullmatch(entry['sha256'])
                    and type(entry.get('bytes')) is int and entry['bytes'] == members[name].size
                    and type(entry.get('width')) is int and type(entry.get('height')) is int,
                    'Invalid preview integrity fields')
            data = source.extractfile(members[name]).read()
            require(digest(data) == entry['sha256'], 'Preview image hash mismatch')
            require(dimensions(data) == (entry['width'], entry['height']), 'Preview dimensions mismatch')
            entries[name] = entry
        require(set(members) == set(entries) | {'index.json'}, 'Unindexed preview member')
    return {'archive_sha256': expected_sha256, 'index_sha256': digest(raw), 'entries': entries}


def clean_flat(directory, parent):
    require(directory.parent == parent and directory.name.startswith('.catalog-previews-')
            and not directory.is_symlink(), 'Unsafe preview cleanup path')
    for child in directory.iterdir():
        require(child.name == 'index.json' or re.fullmatch(r'[0-9a-f]{64}\.webp', child.name),
                'Unexpected preview cleanup member')
        regular(child)
    for child in directory.iterdir():
        child.unlink()
    directory.rmdir()


def exchange(left, right):
    """Linux swaps both directory names without a missing-target interval."""
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    operation = library.renameat2
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def install(archive, expected_sha256, root):
    checked = validate(archive, expected_sha256)
    root = Path(root).absolute()
    require(root.is_dir() and all(not p.is_symlink() for p in (root, *root.parents)),
            'Unsafe preview installation root')
    target = root / 'catalog-previews'
    require(not target.is_symlink() and (not target.exists() or target.is_dir()), 'Unsafe installed preview directory')
    desired = set(checked['entries']) | {'index.json'}
    if target.exists():
        actual = list(target.iterdir())
        require(all(not p.is_symlink() and p.is_file() and
                    (p.name == 'index.json' or re.fullmatch(r'[0-9a-f]{64}\.webp', p.name)) for p in actual),
                'Unexpected installed preview files')
        if {p.name for p in actual} == desired and all(
                regular(p).stat().st_size <= (MAX_INDEX if p.name == 'index.json' else MAX_IMAGE)
                and digest(p.read_bytes()) == (checked['index_sha256'] if p.name == 'index.json'
                                              else checked['entries'][p.name]['sha256']) for p in actual):
            os.chmod(target, 0o755)
            for p in actual:
                os.chmod(p, 0o644)
            return {'changed': False, 'images': len(checked['entries']),
                    'archive_sha256': expected_sha256, 'index_sha256': checked['index_sha256']}
    stage = root / ('.catalog-previews-stage-' + uuid.uuid4().hex)
    backup = root / ('.catalog-previews-old-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    try:
        with tarfile.open(regular(archive), 'r:') as source:
            for member in source:
                require(member.name in desired and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE)
                        and not member.issparse()
                        and 0 < member.size <= (MAX_INDEX if member.name == 'index.json' else MAX_IMAGE),
                        'Preview archive changed during install')
                data = source.extractfile(member).read()
                expected = checked['index_sha256'] if member.name == 'index.json' else checked['entries'][member.name]['sha256']
                require(digest(data) == expected, 'Preview archive changed during install')
                path = stage / member.name
                with path.open('xb') as stream:
                    stream.write(data)
                os.chmod(path, 0o644)
        require({p.name for p in stage.iterdir()} == desired, 'Incomplete preview staging directory')
        os.chmod(stage, 0o755)
        if target.exists() and os.name == 'posix':
            exchange(stage, target)
        else:
            if target.exists():
                target.rename(backup)
            try:
                stage.rename(target)
            except BaseException:
                if backup.exists():
                    backup.rename(target)
                raise
        if backup.exists():
            clean_flat(backup, root)
    finally:
        if stage.exists():
            clean_flat(stage, root)
    return {'changed': True, 'images': len(checked['entries']),
            'archive_sha256': expected_sha256, 'index_sha256': checked['index_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    try:
        import fcntl
        root = args.root.absolute()
        require(root.is_dir() and all(not p.is_symlink() for p in (root, *root.parents)),
                'Unsafe preview installation root')
        lock = root / '.catalog-previews.lock'
        require(not lock.is_symlink(), 'Linked preview lock refused')
        with lock.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            print(json.dumps(install(args.archive, args.sha256, root)))
    except (ValueError, OSError, tarfile.TarError) as exc:
        parser.exit(1, f'Preview installation stopped: {exc}\n')


if __name__ == '__main__':
    main()
