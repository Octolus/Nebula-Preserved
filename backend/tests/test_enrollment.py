"""Bounded first-registration policy and actual HTTP adapter regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import importlib.util
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enrollment import Enrollment, EnrollmentError, decode_body
from public_access import AccessAuthority, AccessDenied, actor_scope, migrate
from server import Backend, parse_args
from state import Store


ACCOUNT = "7656119" + "0000000991"
OTHER = "7656119" + "0000000992"
THIRD = "7656119" + "0000000993"
PEER = "192.0.2.10"


class EnrollmentPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'preservation.sqlite3'
        self.store = Store(self.path)
        migrate(self.store.db)
        self.authority = AccessAuthority(self.store.db)
        self.authority.initialize_operator(b'authored-fixture-operator-key-' * 2)
        self.now = 1700000000
        self.registration = Enrollment(self.store, self.authority, clock=lambda: self.now)
        self.key = secrets.token_urlsafe(32)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def payload(self, account=ACCOUNT, key=None):
        return {'steam_id': account, 'enrollment_key': key or self.key}

    def expect_status(self, status, payload, peer=PEER):
        with self.assertRaises(EnrollmentError) as caught:
            self.registration.register(payload, peer)
        self.assertEqual(caught.exception.status, status)

    def test_new_account_unique_authentication_and_exact_lost_response_retry(self):
        first = self.registration.register(self.payload(), PEER)
        self.assertTrue(first['created'])
        self.assertFalse(first['steam_identity_verified'])
        self.assertEqual(len(first['authorization']), 85)
        self.assertEqual(self.authority.authenticate(first['authorization']), ACCOUNT)
        second = self.registration.register(self.payload(), PEER)
        self.assertFalse(second['created'])
        self.assertEqual(first['authorization'], second['authorization'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM profiles').fetchone()[0], 1)
        self.assertEqual(self.store.db.execute('SELECT provenance_kind FROM preservation_enrollments').fetchone()[0],
                         'preservation-unverified-steam-claim')
        with actor_scope(ACCOUNT), self.assertRaises(AccessDenied):
            self.store.account(OTHER)
        other = self.registration.register(self.payload(OTHER, secrets.token_urlsafe(32)), PEER)
        self.assertNotEqual(first['authorization'], other['authorization'])

    def test_existing_profiles_operator_credentials_and_revocations_are_never_reset(self):
        self.store.account(ACCOUNT)
        original = self.authority.issue(ACCOUNT)
        before = tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone())
        self.expect_status(409, self.payload())
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone()), before)
        self.assertEqual(self.authority.authenticate(original), ACCOUNT)
        self.authority.revoke(ACCOUNT)
        self.expect_status(409, self.payload())
        self.store.account(OTHER)
        self.expect_status(409, self.payload(OTHER))

    def test_repeat_authentication_skips_scrypt_but_honours_revocation_and_rotation(self):
        import public_access
        self.store.account(ACCOUNT)
        original = self.authority.issue(ACCOUNT)
        real = public_access._derive
        with patch.object(public_access, '_derive', side_effect=real) as derive:
            for _ in range(5):
                self.assertEqual(self.authority.authenticate(original), ACCOUNT)
            self.assertEqual(derive.call_count, 1)
            wrong = original[:-1] + ('A' if original[-1] != 'A' else 'B')
            with self.assertRaises(AccessDenied):
                self.authority.authenticate(wrong)
            self.authority.revoke(ACCOUNT)
            with self.assertRaises(AccessDenied):
                self.authority.authenticate(original)
            rotated = self.authority.issue(ACCOUNT)
            with self.assertRaises(AccessDenied):
                self.authority.authenticate(original)
            self.assertEqual(self.authority.authenticate(rotated), ACCOUNT)

    def test_registered_account_wrong_key_revocation_and_ban_cannot_reissue(self):
        registered = self.registration.register(self.payload(), PEER)
        self.expect_status(409, self.payload(key=secrets.token_urlsafe(32)))
        self.assertEqual(self.authority.authenticate(registered['authorization']), ACCOUNT)
        with self.store.atomic():
            self.store.moderation.ban(ACCOUNT, reason='Authored policy test', actor={'id': 'fixture', 'role': 'owner'}, request_id='a' * 32)
        self.expect_status(409, self.payload())
        with self.store.atomic():
            self.store.moderation.unban(ACCOUNT, reason='Authored policy test', actor={'id': 'fixture', 'role': 'owner'}, request_id='b' * 32)
        self.authority.revoke(ACCOUNT)
        self.expect_status(409, self.payload())

    def test_validation_and_duplicate_json_fields_are_bounded(self):
        for malformed in [None, [], {}, {'steam_id': ACCOUNT}, self.payload('not-steam'),
                          self.payload(key='x'), {**self.payload(), 'role': 'owner'}]:
            self.expect_status(400, malformed, '192.0.2.' + str(10 + len(str(malformed)) % 200))
        for raw in [b'{"a":1,"a":2}', b'x' * 1025, b'\xff', b'{']:
            with self.assertRaises((ValueError, UnicodeError)):
                decode_body(raw)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM profiles').fetchone()[0], 0)

    def test_persistent_ip_global_and_total_limits(self):
        self.registration.per_ip = 2
        self.expect_status(400, {})
        self.registration.register(self.payload(), PEER)
        self.expect_status(429, self.payload(OTHER))
        reloaded = Enrollment(self.store, self.authority, clock=lambda: self.now, per_ip=2)
        with self.assertRaises(EnrollmentError) as caught:
            reloaded.register(self.payload(OTHER), PEER)
        self.assertEqual(caught.exception.status, 429)
        self.now += 3600
        self.registration.register(self.payload(OTHER), PEER)
        self.registration.maximum = 2
        self.expect_status(429, self.payload(THIRD), '192.0.2.99')
        self.registration.global_hourly = 2
        self.expect_status(429, self.payload(THIRD), '192.0.2.98')
        stored = [r[0] for r in self.store.db.execute('SELECT bucket FROM preservation_enrollment_limits')]
        self.assertTrue(all(value == 'global' or len(value) == 64 for value in stored))
        self.assertNotIn(PEER, stored)

    def test_failed_registration_rolls_back_profile_and_credential_but_charges_attempt(self):
        issue = self.authority.issue_new
        def fail(*args):
            issue(*args)
            raise RuntimeError('authored transaction fault')
        with patch.object(self.authority, 'issue_new', side_effect=fail), self.assertRaises(RuntimeError):
            self.registration.register(self.payload(), PEER)
        for table in ['profiles', 'profile_state', 'public_access_credentials', 'preservation_enrollments']:
            self.assertEqual(self.store.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT attempts FROM preservation_enrollment_limits WHERE bucket='global'").fetchone()[0], 1)

    def test_concurrent_different_keys_only_one_new_registration_wins(self):
        barrier = threading.Barrier(2)
        def claim(key):
            store = Store(self.path)
            try:
                authority = AccessAuthority(store.db)
                registration = Enrollment(store, authority)
                barrier.wait(timeout=5)
                try:
                    result = registration.register(self.payload(key=key), PEER)
                    return 201 if result['created'] else 200
                except EnrollmentError as error:
                    return error.status
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]))
        self.assertEqual(sorted(results), [201, 409])

    def test_opt_in_arguments_and_no_import_time_creation(self):
        self.assertFalse(parse_args([]).public_enrollment)
        self.assertTrue(parse_args(['--public-access', '--public-enrollment']).public_enrollment)
        with self.assertRaises(SystemExit):
            parse_args(['--public-enrollment'])
        with self.assertRaises(ValueError):
            Backend(Path(self.temp.name) / 'off', public_enrollment=True)

    def test_docker_requires_explicit_public_mode_opt_in(self):
        path = Path(__file__).resolve().parents[2] / 'deployment/docker/entrypoint.py'
        spec = importlib.util.spec_from_file_location('enrollment_entrypoint', path)
        entrypoint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entrypoint)
        pins = {name: 'a' * 64 for name in ['NEBULA_BUILD_REPORT_SHA256', 'NEBULA_SERVER_SHA256', 'NEBULA_MANAGED_SHA256']}
        backend, _, _ = entrypoint.plan(pins)
        self.assertNotIn('--public-enrollment', backend)
        backend, _, _ = entrypoint.plan({**pins, 'NEBULA_MODE': 'public', 'NEBULA_PUBLIC_ENROLLMENT': '1'})
        self.assertIn('--public-access', backend)
        self.assertIn('--public-enrollment', backend)
        for env in [{**pins, 'NEBULA_PUBLIC_ENROLLMENT': '1'}, {**pins, 'NEBULA_MODE': 'public', 'NEBULA_PUBLIC_ENROLLMENT': 'true'}]:
            with self.assertRaises(ValueError):
                entrypoint.plan(env)


class EnrollmentHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'preservation.sqlite3')
        migrate(self.store.db)
        authority = AccessAuthority(self.store.db)
        authority.initialize_operator(b'http-fixture-account-operator-' * 2)
        self.backend = Backend.__new__(Backend)
        self.backend.enrollment = Enrollment(self.store, authority)
        app = web.Application()
        app.router.add_route('*', '/preservation/enroll', self.backend.handle_enrollment)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store.close()
        self.temp.cleanup()

    async def test_actual_http_body_headers_errors_and_disabled_mode(self):
        body = {'steam_id': ACCOUNT, 'enrollment_key': secrets.token_urlsafe(32)}
        headers = {'X-Nebula-Enrollment-IP': PEER}
        response = await self.client.post('/preservation/enroll', json=body, headers=headers)
        self.assertEqual(response.status, 201)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        result = await response.json()
        self.assertEqual(len(result['authorization']), 85)
        response = await self.client.post('/preservation/enroll', json=body, headers=headers)
        self.assertEqual(response.status, 200)
        response = await self.client.post('/preservation/enroll', json=body)
        self.assertEqual(response.status, 400)
        response = await self.client.get('/preservation/enroll')
        self.assertEqual(response.status, 405)
        response = await self.client.post('/preservation/enroll', data=b'{"x":1,"x":2}', headers={**headers, 'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        response = await self.client.post('/preservation/enroll', data=b'x' * 1025, headers={**headers, 'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        self.backend.enrollment = None
        response = await self.client.post('/preservation/enroll', json=body, headers=headers)
        self.assertEqual(response.status, 404)


if __name__ == '__main__':
    unittest.main()
