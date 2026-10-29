"""Publication scanner regressions on authored strings and disposable files."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import audit_public_tree as audit

FIXTURE = 'admin-panel/e2e/panel.spec.ts'
SYNTHETIC = '7656119' + '0000000001'
OTHER = '7656119' + '0000000002'


class ScannerTests(unittest.TestCase):
    def flagged(self, path, content, label='real Steam account ID'):
        return any(row['issue'] == label for row in audit.private_content_issues(path, content))

    def test_only_exact_fixture_value_and_path_are_exempt(self):
        self.assertFalse(self.flagged(FIXTURE, SYNTHETIC))
        for path in ('README.md', 'backend/example.py', 'admin-panel/e2e/other.spec.ts', FIXTURE.upper()):
            with self.subTest(path=path):
                self.assertTrue(self.flagged(path, SYNTHETIC))

    def test_other_account_value_in_fixture_is_reported(self):
        self.assertTrue(self.flagged(FIXTURE, OTHER))
        self.assertTrue(self.flagged(FIXTURE, SYNTHETIC + '\n' + OTHER))

    def test_rust_oracle_exceptions_are_exact_files_and_values(self):
        for path, values in audit.SYNTHETIC_ACCOUNTS.items():
            if not path.startswith('experimental/rust-server/'):
                continue
            for value in values:
                with self.subTest(path=path, value=value):
                    self.assertFalse(self.flagged(path, value))
                    self.assertTrue(self.flagged(path + '.copy', value))
                    self.assertTrue(self.flagged('README.md', value))
            self.assertTrue(self.flagged(path, '7656119' + '9999999999'))

    def test_account_detection_is_retained_elsewhere(self):
        self.assertTrue(self.flagged('backend/data.json', OTHER))
        self.assertFalse(self.flagged('README.md', 'Steam account IDs must not be published'))

    def test_other_secret_patterns_still_apply_in_fixture(self):
        marker = '-----BEGIN ' + 'PRIVATE KEY-----'
        self.assertTrue(self.flagged(FIXTURE, SYNTHETIC + '\n' + marker, 'private key'))
        token = 'ghp_' + 'A' * 40
        self.assertTrue(self.flagged(FIXTURE, token, 'GitHub token'))

    def test_private_path_rule_is_retained(self):
        value = 'C:' + chr(92) + 'Users' + chr(92) + 'fixture-person' + chr(92) + 'private.txt'
        self.assertTrue(self.flagged('README.md', value, 'private workspace path'))

    def test_main_scans_all_files_and_keeps_nonzero_exit_for_other_id(self):
        with tempfile.TemporaryDirectory(prefix='nebula-public-audit-') as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            fixture = root / FIXTURE
            fixture.parent.mkdir(parents=True)
            fixture.write_text(SYNTHETIC, encoding='utf-8')
            (root / 'README.md').write_text(OTHER, encoding='utf-8')
            result = SimpleNamespace(stdout=(FIXTURE + '\0README.md\0').encode())
            output = io.StringIO()
            with patch.object(audit, 'ROOT', root), patch.object(audit.subprocess, 'run', return_value=result), contextlib.redirect_stdout(output):
                code = audit.main()
            report = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(report['files_checked'], 2)
            self.assertEqual(report['issues'], [{'path': 'README.md', 'issue': 'real Steam account ID'}])


if __name__ == '__main__':
    unittest.main()
