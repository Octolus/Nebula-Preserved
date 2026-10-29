"""Inventory checks use real disposable Git repositories, never the checkout index."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import update_source_inventory as inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '--quiet', str(self.root)], check=True)
        (self.root/'README.md').write_text('Example source\n', encoding='utf-8')
        (self.root/'.gitignore').write_text('private/\n', encoding='utf-8')
        (self.root/'SOURCE-INVENTORY.json').write_text(json.dumps({
            'files': {}, 'file_count_excluding_inventory': 0, 'bytes_excluding_inventory': 0,
            'validation': {'native_acceptance': 'not claimed'},
        }), encoding='utf-8')

    def test_refresh_and_check_preserve_validation_and_exclude_private_files(self):
        (self.root/'private').mkdir()
        (self.root/'private'/'credential.txt').write_text('synthetic secret', encoding='utf-8')
        result = inventory.refresh(self.root, write=True)
        self.assertEqual(result['files'], 3)
        value = json.loads((self.root/'SOURCE-INVENTORY.json').read_bytes())
        self.assertEqual(set(value['files']), {'.gitignore', 'README.md'})
        self.assertEqual(value['validation'], {'native_acceptance': 'not claimed'})
        self.assertEqual(inventory.refresh(self.root, write=False)['files'], 3)

    def test_modified_missing_and_extra_sources_fail_check(self):
        inventory.refresh(self.root, write=True)
        (self.root/'README.md').write_text('Changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            inventory.refresh(self.root, write=False)
        inventory.refresh(self.root, write=True)
        (self.root/'extra.py').write_text('pass\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            inventory.refresh(self.root, write=False)
        (self.root/'extra.py').unlink()
        (self.root/'README.md').unlink()
        with self.assertRaisesRegex(ValueError, 'stale'):
            inventory.refresh(self.root, write=False)

    def test_nested_directory_cannot_inventory_the_parent_repository(self):
        nested = self.root/'nested'
        nested.mkdir()
        with self.assertRaisesRegex(ValueError, 'surrounding'):
            inventory.collect(nested)

    def test_a_tracked_ignored_file_is_not_silently_omitted(self):
        (self.root/'private').mkdir()
        (self.root/'private'/'mistaken.txt').write_text('fixture', encoding='utf-8')
        subprocess.run(['git', 'add', '--force', 'private/mistaken.txt'], cwd=self.root, check=True)
        self.assertIn('private/mistaken.txt', inventory.collect(self.root))

    def test_concurrent_source_change_preserves_previous_inventory(self):
        before = (self.root/'SOURCE-INVENTORY.json').read_bytes()
        real_collect = inventory.collect
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.root/'README.md').write_text('Concurrent edit', encoding='utf-8')
            return real_collect(*args, **kwargs)

        with patch.object(inventory, 'collect', changing):
            with self.assertRaisesRegex(ValueError, 'Concurrent'):
                inventory.refresh(self.root, write=True)
        self.assertEqual((self.root/'SOURCE-INVENTORY.json').read_bytes(), before)
        self.assertEqual(list(self.root.glob('.source-inventory-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
