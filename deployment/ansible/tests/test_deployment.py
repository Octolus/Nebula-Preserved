"""Offline bootstrap checks; no service, network or package installation."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nebula_secret_bootstrap', ROOT / 'files/bootstrap-secrets.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('openssl'), 'Linux and OpenSSL required')
class SecretBootstrapTests(unittest.TestCase):
    """Real TLS certificates and password derivation, isolated in temporary trees."""

    @classmethod
    def setUpClass(cls):
        cls.reference = tempfile.TemporaryDirectory(prefix='nebula-bootstrap-reference-')
        cls.reference_root = Path(cls.reference.name)
        cls.invoke(cls.reference_root)

    @classmethod
    def tearDownClass(cls):
        cls.reference.cleanup()

    @staticmethod
    def invoke(root, address='192.0.2.10', tls_mode='private_ca'):
        # Tests do not need root and must never chown a developer's files.
        original_umask = os.umask(0o077)
        try:
            with patch.object(BOOTSTRAP.os, 'chown'), contextlib.redirect_stdout(io.StringIO()):
                BOOTSTRAP.bootstrap(root, address, tls_mode)
        finally:
            os.umask(original_umask)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nebula-bootstrap-test-')
        self.root = Path(self.temporary.name)
        shutil.copytree(self.reference_root, self.root, dirs_exist_ok=True)

    def tearDown(self):
        self.temporary.cleanup()

    def hashes(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_repeat_keeps_password_tokens_and_entire_tls_identity(self):
        before = self.hashes()
        self.invoke(self.root)
        self.assertEqual(before, self.hashes())

    def test_migration_to_public_tls_retains_ca_account_and_operator_authorities(self):
        before = self.hashes()
        self.invoke(self.root, tls_mode='public_acme')
        self.assertEqual(before, self.hashes())

    def test_fresh_public_mode_creates_no_private_ca_or_self_signed_certificate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(BOOTSTRAP.subprocess, 'run') as run:
                self.invoke(root, tls_mode='public_acme')
                run.assert_not_called()
            self.assertTrue((root / 'operator/account-operator.key').is_file())
            self.assertTrue((root / 'operator/panel-login.txt').is_file())
            self.assertFalse((root / 'operator/ca-key.pem').exists())
            self.assertFalse((root / 'secrets/fullchain.pem').exists())

    def test_generated_login_matches_panel_scrypt_format(self):
        login = (self.root / 'operator/panel-login.txt').read_text()
        password = login.split('Password: ', 1)[1].strip()
        self.assertGreaterEqual(len(password), 32)
        config = json.loads((self.root / 'secrets/admin-operators.json').read_text())
        operator = config['operators'][0]
        self.assertEqual(('owner', 'owner', True), (operator['id'], operator['role'], operator['enabled']))
        scheme, n, r, p, salt, expected = operator['password_scrypt'].split('$')
        self.assertEqual(('scrypt', '16384', '8', '1'), (scheme, n, r, p))
        actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=int(n), r=int(r), p=int(p), dklen=32)
        self.assertEqual(expected, actual.hex())
        self.assertEqual(64, len((self.root / 'secrets/admin-token.txt').read_text()))

    def test_runtime_secrets_have_no_world_access(self):
        self.invoke(self.root)
        self.assertEqual(0o700, stat.S_IMODE((self.root / 'operator').stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE((self.root / 'secrets').stat().st_mode))
        for path in (self.root / 'secrets').iterdir():
            self.assertEqual(0o440, stat.S_IMODE(path.stat().st_mode), path.name)
        for name in ('ca-key.pem', 'panel-login.txt'):
            self.assertEqual(0, stat.S_IMODE((self.root / 'operator' / name).stat().st_mode) & 0o077)

    def test_new_address_does_not_silently_replace_certificate(self):
        before = self.hashes()
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke(self.root, '192.0.2.11')
        self.assertEqual(before, self.hashes())

    def test_invalid_address_writes_nothing(self):
        for value in ('not-an-ip', '192.0.2.10;id', '999.2.3.4', '::1', '192.0.2.10\n'):
            with self.subTest(address=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    self.invoke(Path(directory), value)
                self.assertEqual([], list(Path(directory).iterdir()))

    def test_partial_initial_credentials_fail_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'secrets').mkdir()
            token = root / 'secrets/admin-token.txt'
            token.write_text('existing operator token')
            with self.assertRaisesRegex(RuntimeError, 'Partial secret'):
                self.invoke(root)
            self.assertEqual('existing operator token', token.read_text())
            self.assertFalse((root / 'operator/ca-key.pem').exists())

    def test_partial_pki_does_not_replace_existing_ca_key(self):
        (self.root / 'operator/ca.pem').unlink()
        key = self.root / 'operator/ca-key.pem'
        before = key.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Partial PKI'):
            self.invoke(self.root)
        self.assertEqual(before, key.read_bytes())

    def test_expiry_check_failure_keeps_credentials_and_keys(self):
        before = self.hashes()
        actual_run = subprocess.run

        def expire(command, **kwargs):
            if '-checkend' in command:
                self.assertIn('2592000', command)
                raise subprocess.CalledProcessError(1, command)
            return actual_run(command, **kwargs)

        with patch.object(BOOTSTRAP.subprocess, 'run', side_effect=expire):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(self.root)
        self.assertEqual(before, self.hashes())

    def test_linked_runtime_secret_is_rejected_without_touching_target(self):
        target = self.root / 'operator/foreign-token.txt'
        target.write_text('leave this untouched')
        linked = self.root / 'secrets/admin-token.txt'
        linked.unlink()
        linked.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.invoke(self.root)
        self.assertEqual('leave this untouched', target.read_text())

    def test_missing_completed_credential_refuses_without_rotation(self):
        (self.root / 'secrets/panel-session-key.txt').unlink()
        before = self.hashes()
        with self.assertRaisesRegex(RuntimeError, 'Incomplete operator'):
            self.invoke(self.root)
        self.assertEqual(before, self.hashes())

    def test_linked_ca_key_refuses_without_reading_or_writing_target(self):
        key = self.root / 'operator/ca-key.pem'
        target = self.root / 'untouched.pem'
        target.write_bytes(key.read_bytes())
        key.unlink()
        key.symlink_to(target)
        before = self.hashes()
        with self.assertRaisesRegex(RuntimeError, 'Non-regular secret'):
            self.invoke(self.root)
        self.assertEqual(before, self.hashes())

    def test_mismatched_leaf_key_refuses_without_rotation(self):
        key = self.root / 'secrets/server-key.pem'
        key.chmod(0o600)
        key.write_bytes((self.root / 'operator/ca-key.pem').read_bytes())
        before = self.hashes()
        with self.assertRaisesRegex(RuntimeError, 'do not match'):
            self.invoke(self.root)
        self.assertEqual(before, self.hashes())


if __name__ == '__main__':
    unittest.main()
