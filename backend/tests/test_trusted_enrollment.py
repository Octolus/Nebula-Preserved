"""Trusted claimed-ID devices keep existing account state and credentials."""
import hashlib
from pathlib import Path
import secrets
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enrollment import Enrollment, EnrollmentError
from public_access import AccessAuthority, AccessDenied
from remote_gateway import Authority, Denied
from state import Store
from server import parse_args
import test_enrollment as fixture
ACCOUNT, OTHER, PEER = fixture.ACCOUNT, fixture.OTHER, fixture.PEER


class TrustedClaims(unittest.TestCase):
    setUp = fixture.EnrollmentPolicy.setUp
    tearDown = fixture.EnrollmentPolicy.tearDown
    payload = fixture.EnrollmentPolicy.payload

    def trusted(self):
        self.registration = Enrollment(self.store, self.authority, trust_steam_id=True)
        return self.registration

    def test_two_devices_keep_same_profile_state_and_old_primary(self):
        self.store.account(ACCOUNT, 'Original Character')
        primary = self.authority.issue(ACCOUNT)
        original = tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone())
        with self.store.db:
            self.store.db.execute('UPDATE profile_state SET last_preset=? WHERE ps4_id=?', ('kept-avatar-preset', ACCOUNT))
        profile = tuple(self.store.db.execute('SELECT * FROM profiles').fetchone())
        state = tuple(self.store.db.execute('SELECT * FROM profile_state').fetchone())
        self.trusted()
        a = self.registration.register(self.payload(), PEER)
        b = self.registration.register(self.payload(key=secrets.token_urlsafe(32)), PEER)
        self.assertFalse(a['created']); self.assertFalse(b['created'])
        for credential in [primary, a['authorization'], b['authorization']]:
            self.assertEqual(self.authority.authenticate(credential), ACCOUNT)
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone()), original)
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM profiles').fetchone()), profile)
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM profile_state').fetchone()), state)
        self.assertEqual(self.registration.register(self.payload(), PEER)['authorization'], a['authorization'])

    def test_new_claim_persists_without_primary_and_strict_mode_disables_aliases(self):
        self.trusted()
        credential = self.registration.register(self.payload(), PEER)
        self.assertTrue(credential['created'])
        self.assertIsNone(self.store.db.execute('SELECT 1 FROM public_access_credentials').fetchone())
        fresh = Store(self.path)
        try:
            independent = AccessAuthority(fresh.db)
            self.assertEqual(independent.authenticate(credential['authorization']), ACCOUNT)
            Enrollment(self.store, self.authority, trust_steam_id=False)
            with self.assertRaises(AccessDenied): independent.authenticate(credential['authorization'])
            self.trusted()
            self.assertEqual(independent.authenticate(credential['authorization']), ACCOUNT)
        finally:
            fresh.close()

    def test_revoked_primary_can_claim_new_device_but_active_ban_cannot(self):
        self.store.account(ACCOUNT)
        primary = self.authority.issue(ACCOUNT)
        self.authority.revoke(ACCOUNT)
        original = tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone())
        self.trusted()
        claim = self.registration.register(self.payload(), PEER)
        self.assertEqual(self.authority.authenticate(claim['authorization']), ACCOUNT)
        with self.assertRaises(AccessDenied): self.authority.authenticate(primary)
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM public_access_credentials').fetchone()), original)
        with self.store.atomic():
            self.store.moderation.ban(ACCOUNT, reason='Authored policy test', actor={'id': 'fixture', 'role': 'owner'}, request_id='c' * 32)
        with self.assertRaises(EnrollmentError) as caught:
            self.registration.register(self.payload(key=secrets.token_urlsafe(32)), PEER)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'account_banned'))
        with self.assertRaises(AccessDenied): self.authority.authenticate(claim['authorization'])

    def gateway(self):
        guid = 'd' * 32
        self.store.bind_session(ACCOUNT, guid)
        with self.store.db:
            self.store.db.execute('INSERT INTO allocations VALUES(?,?,?,?,?,?)',
                                 (guid, 'trusted-fixture-instance', 'Nexus', '127.0.0.1', 40120, time.time()))
        gateway = Authority(self.path.parent, 40120, 40120)
        class Directory:
            def all_ready(self):
                return [{'instance_id': 'trusted-fixture-instance', 'psidglobal': 'Nexus',
                         'ip': '127.0.0.1', 'bind': '127.0.0.1', 'port': 40120, 'heartbeat': time.time()}]
        gateway.instances = Directory()
        return gateway

    def test_real_gateway_auth_and_revalidation_bind_exact_device(self):
        self.trusted()
        a = self.registration.register(self.payload(), PEER)
        b = self.registration.register(self.payload(key=secrets.token_urlsafe(32)), PEER)
        gateway = self.gateway()
        left = gateway.resolve(40120, a['authorization'])
        right = gateway.resolve(40120, b['authorization'])
        self.assertEqual(left['account'], right['account'])
        self.assertNotEqual(left['claimed_device'], right['claimed_device'])
        self.assertNotEqual(left['credential'], right['credential'])
        self.assertEqual(gateway.resolve(40120, expected=left), left)
        with self.store.db:
            self.store.db.execute('UPDATE public_access_claimed_devices SET revoked_at=1 WHERE ps4_id=? AND key_hash=?',
                                 (ACCOUNT, left['claimed_device']))
        with self.assertRaises(Denied): gateway.resolve(40120, expected=left)
        self.assertEqual(gateway.resolve(40120, expected=right), right)
        Enrollment(self.store, self.authority, trust_steam_id=False)
        with self.assertRaises(Denied): gateway.resolve(40120, expected=right)

    def test_trusted_limits_are_explicit_and_aliases_remain_account_scoped(self):
        self.trusted()
        self.assertEqual((self.registration.per_ip, self.registration.global_hourly), (120, 1200))
        a = self.registration.register(self.payload(), PEER)
        b = self.registration.register(self.payload(OTHER, secrets.token_urlsafe(32)), PEER)
        altered = a['authorization'].rsplit('.', 1)[0] + '.' + b['authorization'].rsplit('.', 1)[1]
        with self.assertRaises(AccessDenied): self.authority.authenticate(altered)
        self.assertEqual(self.authority.authenticate(a['authorization']), ACCOUNT)
        self.assertEqual(self.authority.authenticate(b['authorization']), OTHER)

    def test_explicit_flag_and_device_capacity_preserve_existing_keys(self):
        self.assertFalse(parse_args([]).trust_steam_id)
        self.assertTrue(parse_args(['--public-access', '--public-enrollment', '--trust-steam-id']).trust_steam_id)
        with self.assertRaises(SystemExit): parse_args(['--public-access', '--trust-steam-id'])
        self.trusted()
        first = self.registration.register(self.payload(), PEER)
        with self.store.db:
            for number in range(63):
                self.store.db.execute('INSERT INTO public_access_claimed_devices VALUES(?,?,?,?,?,NULL)',
                                     (ACCOUNT, hashlib.sha256(('authored-capacity-' + str(number)).encode()).hexdigest(),
                                      b's' * 16, b'v' * 32, time.time()))
        with self.assertRaises(EnrollmentError) as caught:
            self.registration.register(self.payload(key=secrets.token_urlsafe(32)), PEER)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(self.registration.register(self.payload(), PEER)['authorization'], first['authorization'])
        self.assertEqual(self.authority.authenticate(first['authorization']), ACCOUNT)


class TrustedHTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixture.EnrollmentHTTP.asyncSetUp(self)
        self.backend.enrollment = Enrollment(self.store, AccessAuthority(self.store.db), trust_steam_id=True)

    asyncTearDown = fixture.EnrollmentHTTP.asyncTearDown

    async def test_existing_profile_two_http_devices_keep_original_character(self):
        self.store.account(ACCOUNT, 'Saved Original')
        authority = AccessAuthority(self.store.db)
        primary = authority.issue(ACCOUNT)
        with self.store.db:
            self.store.db.execute('UPDATE profile_state SET last_preset=? WHERE ps4_id=?', ('saved-character', ACCOUNT))
        credentials = []
        for _ in range(2):
            response = await self.client.post('/preservation/enroll', json={
                'steam_id': ACCOUNT, 'enrollment_key': secrets.token_urlsafe(32)},
                headers={'X-Nebula-Enrollment-IP': PEER})
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertFalse(body['created'])
            credentials.append(body['authorization'])
        for credential in [primary, *credentials]:
            self.assertEqual(authority.authenticate(credential), ACCOUNT)
        self.assertEqual(self.store.db.execute('SELECT username FROM profiles WHERE ps4_id=?', (ACCOUNT,)).fetchone()[0], 'Saved Original')
        self.assertEqual(self.store.db.execute('SELECT last_preset FROM profile_state WHERE ps4_id=?', (ACCOUNT,)).fetchone()[0], 'saved-character')


if __name__ == '__main__': unittest.main()
