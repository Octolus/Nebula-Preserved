"""Public TLS policy/publication tests; never contact ACME or operate Docker."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_tls', ROOT / 'files/manage-public-tls.py')
TLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TLS)


class PublicTlsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nebula-public-tls-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'acme').mkdir()

    def test_public_mode_refuses_local_reserved_noncanonical_and_injected_addresses(self):
        for address in ('127.0.0.1', '10.0.0.1', '192.0.2.10', '0.0.0.0', '01.1.1.1',
                        '::1', '1.1.1.1\n', '1.1.1.1;id'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                TLS.public_address(address)
        self.assertEqual('1.1.1.1', TLS.public_address('1.1.1.1'))

    def test_issue_uses_pinned_image_short_lived_ip_http_challenge_without_host_network(self):
        command = TLS.certbot_command(self.root, '1.1.1.1', 'issue')
        self.assertIn(TLS.CERTBOT_IMAGE, command)
        self.assertRegex(TLS.CERTBOT_IMAGE, r'@sha256:[a-f0-9]{64}$')
        for flag in ('--read-only', '--webroot', '--ip-address', '--keep-until-expiring'):
            self.assertIn(flag, command)
        self.assertEqual('shortlived', command[command.index('--preferred-profile') + 1])
        self.assertNotIn('--privileged', command)
        self.assertNotIn('--network', command)
        self.assertTrue(any(value.startswith('/tmp:rw,') for value in command))

    def test_renew_keeps_existing_identity_and_has_no_unnecessary_forced_renewal(self):
        command = TLS.certbot_command(self.root, '1.1.1.1', 'renew')
        self.assertIn('renew', command)
        self.assertIn('--no-random-sleep-on-renew', command)
        self.assertNotIn('--force-renewal', command)
        self.assertNotIn('--agree-tos', command)

    def test_preflight_is_staging_dry_run_with_distinct_lineage(self):
        command = TLS.certbot_command(self.root, '1.1.1.1', 'preflight')
        self.assertIn('--dry-run', command)
        self.assertIn('nebula-preflight', command)
        self.assertNotIn(TLS.ACME_SERVER, command)
        self.assertNotIn(TLS.CERT_NAME, command)

    def test_unknown_operation_does_not_execute(self):
        with patch.object(TLS.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                TLS.certbot_command(self.root, '1.1.1.1', 'delete')
            run.assert_not_called()

    def test_certificate_validation_checks_system_chain_ip_validity_key_and_fullchain(self):
        leaf, chain, key = self.root / 'cert.pem', self.root / 'chain.pem', self.root / 'key.pem'
        fullchain = self.root / 'fullchain.pem'
        leaf.write_bytes(b'leaf\n')
        chain.write_bytes(b'chain\n')
        key.write_bytes(b'private\n')
        fullchain.write_bytes(b'leaf\nchain\n')
        files = {'cert.pem': leaf, 'chain.pem': chain, 'privkey.pem': key, 'fullchain.pem': fullchain}
        with patch.object(TLS, 'resolve_acme_file', side_effect=lambda root, name: files[name]), \
                patch.object(TLS, 'run', return_value=types.SimpleNamespace(stdout=b'public key')) as run:
            self.assertEqual((b'leaf\nchain\n', b'private\n'), TLS.validate_certificate(self.root, '1.1.1.1'))
            verify = run.call_args_list[0].args[0]
            self.assertIn('-verify_ip', verify)
            self.assertIn('-purpose', verify)
            self.assertIn('sslserver', verify)
            self.assertNotIn('-CAfile', verify)
            self.assertIn('86400', run.call_args_list[1].args[0])
            fullchain.write_bytes(b'other chain\n')
            with self.assertRaisesRegex(RuntimeError, 'fullchain'):
                TLS.validate_certificate(self.root, '1.1.1.1')

    def test_key_mismatch_is_rejected_before_runtime_publication(self):
        paths = {name: self.root / name for name in ('cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem')}
        for path in paths.values():
            path.write_bytes(b'fixture')
        results = [types.SimpleNamespace(stdout=b''), types.SimpleNamespace(stdout=b''),
                   types.SimpleNamespace(stdout=b'certificate public'), types.SimpleNamespace(stdout=b'other public')]
        with patch.object(TLS, 'resolve_acme_file', side_effect=lambda root, name: paths[name]), \
                patch.object(TLS, 'run', side_effect=results):
            with self.assertRaisesRegex(RuntimeError, 'do not match'):
                TLS.validate_certificate(self.root, '1.1.1.1')
            self.assertFalse((self.root / 'secrets').exists())

    def test_pair_publication_is_idempotent_and_does_not_touch_account_authority(self):
        operator = self.root / 'operator'
        operator.mkdir()
        (operator / 'account-operator.key').write_bytes(b'unchanged account authority')
        with patch.object(TLS.os, 'chown', create=True):
            self.assertTrue(TLS.install_pair(self.root, b'certificate', b'key'))
            self.assertFalse(TLS.install_pair(self.root, b'certificate', b'key'))
        self.assertEqual(b'unchanged account authority', (operator / 'account-operator.key').read_bytes())

    def test_staging_failure_keeps_existing_runtime_pair(self):
        with patch.object(TLS.os, 'chown', create=True):
            TLS.install_pair(self.root, b'old certificate', b'old key')
        before = {path.name: path.read_bytes() for path in (self.root / 'secrets').iterdir()}
        with patch.object(TLS.os, 'chown', side_effect=OSError('cannot set permissions'), create=True):
            with self.assertRaises(OSError):
                TLS.install_pair(self.root, b'new certificate', b'new key')
        self.assertEqual(before, {path.name: path.read_bytes() for path in (self.root / 'secrets').iterdir()})

    def test_failed_sidecar_refresh_is_retried_even_when_files_already_match(self):
        with patch.object(TLS.os, 'chown', create=True), \
                patch.object(TLS.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
                patch.object(TLS, 'run', side_effect=subprocess.CalledProcessError(1, ['docker'])):
            with self.assertRaises(subprocess.CalledProcessError):
                TLS.activate_pair(self.root, b'certificate', b'key')
        self.assertFalse((self.root / 'acme/runtime-certificate.sha256').exists())
        with patch.object(TLS.os, 'chown', create=True), \
                patch.object(TLS.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
                patch.object(TLS, 'run') as run:
            result = TLS.activate_pair(self.root, b'certificate', b'key')
            self.assertFalse(result['runtime_files_changed'])
            self.assertTrue(result['tls_sidecars_refreshed'])
            command = run.call_args.args[0]
            self.assertIn('--force-recreate', command)
            self.assertEqual(['public-https', 'public-game', 'panel-https'], command[-3:])
        self.assertEqual(hashlib.sha256(b'certificate').hexdigest(),
                         (self.root / 'acme/runtime-certificate.sha256').read_text().strip())

    def test_deferred_or_inactive_refresh_does_not_touch_running_services(self):
        for active, refresh in ((True, False), (False, True)):
            with self.subTest(active=active), patch.object(TLS.os, 'chown', create=True), \
                    patch.object(TLS.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0 if active else 3)), \
                    patch.object(TLS, 'run') as run:
                result = TLS.activate_pair(self.root, b'certificate', b'key', refresh)
                run.assert_not_called()
                self.assertFalse(result['tls_sidecars_refreshed'])
                self.assertFalse((self.root / 'acme/runtime-certificate.sha256').exists())

    def test_unknown_deployment_root_is_refused_before_docker(self):
        with patch.object(TLS, 'run') as run:
            with self.assertRaises(ValueError):
                TLS.manage(self.root, '1.1.1.1', 'issue')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
