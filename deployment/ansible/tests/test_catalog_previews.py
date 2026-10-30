"""Private preview packs fail closed before replacing any active directory."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('preview_installer', ROOT / 'deployment/ansible/files/install-catalog-previews.py')
PACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACK)


def webp(width=2, height=3):
    payload = b'\x2f' + ((width - 1) | ((height - 1) << 14)).to_bytes(4, 'little')
    chunk = b'VP8L' + len(payload).to_bytes(4, 'little') + payload + b'\0'
    return b'RIFF' + (len(chunk) + 4).to_bytes(4, 'little') + b'WEBP' + chunk


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nebula-preview-tests-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / 'input.tar'
        self.image = webp()
        self.key = hashlib.sha256(b'MALE/resource.png').hexdigest()
        self.entry = {'key': self.key, 'filename': self.key + '.webp', 'sha256': PACK.digest(self.image),
                      'bytes': len(self.image), 'width': 2, 'height': 3, 'source_kind': 'shipped_sprite'}

    def write(self, entries=None, extras=None, image=None, raw_index=None):
        entries = [self.entry] if entries is None else entries
        data = json.dumps({'format_version': 1, 'entries': entries}).encode() if raw_index is None else raw_index
        members = [('index.json', data), (self.entry['filename'], self.image if image is None else image)]
        with tarfile.open(self.archive, 'w') as stream:
            for name, content in members + (extras or []):
                info = tarfile.TarInfo(name)
                if content is None:
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/outside'
                    stream.addfile(info)
                else:
                    info.size = len(content)
                    stream.addfile(info, io.BytesIO(content))
        return PACK.digest(self.archive.read_bytes())

    def test_install_repeat_and_repair_are_content_verified(self):
        sha = self.write()
        first = PACK.install(self.archive, sha, self.root)
        self.assertTrue(first['changed'])
        self.assertFalse(PACK.install(self.archive, sha, self.root)['changed'])
        target = self.root / 'catalog-previews' / self.entry['filename']
        target.write_bytes(b'corrupted')
        self.assertTrue(PACK.install(self.archive, sha, self.root)['changed'])
        self.assertEqual(self.image, target.read_bytes())
        self.assertFalse(any(p.name.startswith('.catalog-previews-') for p in self.root.iterdir()))

    def test_archive_hash_fails_before_creating_pack(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            PACK.install(self.archive, '0' * 64, self.root)
        self.assertFalse((self.root / 'catalog-previews').exists())

    def test_unsafe_duplicate_unindexed_and_link_members(self):
        for name, value in [('../outside', b'x'), ('folder/file', b'x'), ('/absolute', b'x'),
                            ('index.json', b'{}'), ('a' * 64 + '.webp', b'unknown'),
                            ('b' * 64 + '.webp', None), ('folder/', None)]:
            with self.subTest(name=name):
                sha = self.write(extras=[(name, value)])
                with self.assertRaises(ValueError):
                    PACK.validate(self.archive, sha)

    def test_missing_duplicate_malformed_and_unknown_index(self):
        for raw in [b'{', b'{"format_version":1,"format_version":1,"entries":[]}',
                    b'{"format_version":true,"entries":[]}', b'{"format_version":2,"entries":[]}']:
            with self.subTest(raw=raw):
                sha = self.write(raw_index=raw)
                with self.assertRaises(ValueError):
                    PACK.validate(self.archive, sha)
        sha = self.write(entries=[self.entry, self.entry])
        with self.assertRaises(ValueError):
            PACK.validate(self.archive, sha)
        sha = self.write(entries=[dict(self.entry, key='f' * 64, filename='f' * 64 + '.webp')])
        with self.assertRaises(ValueError):
            PACK.validate(self.archive, sha)

    def test_hash_size_dimensions_and_container_mismatch(self):
        for field, value in [('sha256', '0' * 64), ('bytes', 1), ('width', 1), ('height', True),
                             ('filename', '../escape.webp')]:
            with self.subTest(field=field):
                sha = self.write(entries=[dict(self.entry, **{field: value})])
                with self.assertRaises(ValueError):
                    PACK.validate(self.archive, sha)
        bad = b'invalid'
        sha = self.write(image=bad, entries=[dict(self.entry, bytes=len(bad), sha256=PACK.digest(bad))])
        with self.assertRaisesRegex(ValueError, 'WebP'):
            PACK.validate(self.archive, sha)

    def test_resource_limits(self):
        for name, value in [('MAX_IMAGE', 1), ('MAX_INDEX', 1), ('MAX_TOTAL', 1), ('MAX_IMAGES', 0)]:
            sha = self.write()
            with self.subTest(limit=name), patch.object(PACK, name, value), self.assertRaises(ValueError):
                PACK.validate(self.archive, sha)

    def test_invalid_replacement_preserves_old_pack(self):
        sha = self.write()
        PACK.install(self.archive, sha, self.root)
        before = {p.name: p.read_bytes() for p in (self.root / 'catalog-previews').iterdir()}
        sha = self.write(entries=[dict(self.entry, width=99)])
        with self.assertRaises(ValueError):
            PACK.install(self.archive, sha, self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'catalog-previews').iterdir()})

    def test_swap_failure_rolls_back_and_cleans_stage(self):
        target = self.root / 'catalog-previews'
        target.mkdir()
        (target / 'index.json').write_text('previous')
        rename = Path.rename
        def fail_stage(path, destination):
            if path.name.startswith('.catalog-previews-stage-'):
                raise OSError('injected activation failure')
            return rename(path, destination)
        sha = self.write()
        with patch.object(Path, 'rename', fail_stage), patch.object(PACK, 'exchange', side_effect=OSError('injected exchange failure')), self.assertRaises(OSError):
            PACK.install(self.archive, sha, self.root)
        self.assertEqual('previous', (target / 'index.json').read_text())
        self.assertFalse(any(p.name.startswith('.catalog-previews-') for p in self.root.iterdir()))

    def test_foreign_directory_contents_are_never_removed(self):
        target = self.root / 'catalog-previews'
        target.mkdir()
        (target / 'operator-file').write_text('keep')
        sha = self.write()
        with self.assertRaisesRegex(ValueError, 'Unexpected installed'):
            PACK.install(self.archive, sha, self.root)
        self.assertEqual('keep', (target / 'operator-file').read_text())

    def test_symlink_target_archive_and_link_parent_refused(self):
        sha = self.write()
        link = self.root / 'linked.tar'
        try:
            link.symlink_to(self.archive)
        except OSError:
            self.skipTest('OS does not grant unprivileged symlink creation')
        with self.assertRaises(ValueError):
            PACK.validate(link, sha)
        target = self.root / 'catalog-previews'
        target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            PACK.install(self.archive, sha, self.root)


if __name__ == '__main__':
    unittest.main()
