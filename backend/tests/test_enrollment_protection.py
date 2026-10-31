"""Trusted claimed-ID enrollment cannot take over protected accounts; limits are operator-configurable."""
from pathlib import Path
import secrets
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enrollment import Enrollment, EnrollmentError, enrollment_policy
import test_enrollment as fixture
ACCOUNT, OTHER, THIRD, PEER = fixture.ACCOUNT, fixture.OTHER, fixture.THIRD, fixture.PEER
OWNER = {'id': 'fixture', 'role': 'owner'}


class ProtectedTrustedClaims(unittest.TestCase):
    setUp = fixture.EnrollmentPolicy.setUp
    tearDown = fixture.EnrollmentPolicy.tearDown
    payload = fixture.EnrollmentPolicy.payload

    def trusted(self, **options):
        return Enrollment(self.store, self.authority, trust_steam_id=True, env={}, **options)

    def refused(self, registration, account, key=None):
        devices = self.store.db.execute('SELECT count(*) FROM public_access_claimed_devices').fetchone()[0]
        with self.assertRaises(EnrollmentError) as caught:
            registration.register(self.payload(account, key or secrets.token_urlsafe(32)), PEER)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'account_unavailable'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM public_access_claimed_devices').fetchone()[0],
                         devices)

    def test_staff_labelled_account_needs_its_primary_credential(self):
        self.store.account(ACCOUNT)
        primary = self.authority.issue(ACCOUNT)
        with self.store.atomic():
            self.store.moderation.set_staff_label(ACCOUNT, 'Staff', reason='Authored policy test', actor=OWNER,
                                                  request_id='d' * 32)
        registration = self.trusted()
        self.refused(registration, ACCOUNT)
        retry = registration.register(self.payload(ACCOUNT, primary.rsplit('.', 1)[1]), PEER)
        self.assertEqual((retry['authorization'], retry['created']), (primary, False))
        # Unprotected accounts keep the owner's trusted-claim policy.
        self.store.account(OTHER)
        self.assertFalse(registration.register(self.payload(OTHER), PEER)['created'])
        # Opting out restores plain trusted claims for staff accounts too.
        self.assertFalse(self.trusted(protect_staff=False).register(self.payload(ACCOUNT), PEER)['created'])

    def test_dashboard_operator_link_and_listed_accounts_are_protected(self):
        for account in (ACCOUNT, OTHER, THIRD):
            self.store.account(account)
        with self.store.db:
            self.store.db.execute('CREATE TABLE management_operator_accounts (operator_id TEXT PRIMARY KEY, '
                                  'account_id TEXT NOT NULL UNIQUE)')
            self.store.db.execute('INSERT INTO management_operator_accounts VALUES(?,?)', ('owner', ACCOUNT))
        registration = Enrollment(self.store, self.authority, trust_steam_id=True,
                                  env={'NEBULA_PROTECTED_ACCOUNTS': OTHER})
        self.refused(registration, ACCOUNT)
        self.refused(registration, OTHER)  # No primary credential exists: never claimable.
        self.assertFalse(registration.register(self.payload(THIRD), PEER)['created'])
        # A listed account stays protected even when staff protection is disabled.
        relaxed = Enrollment(self.store, self.authority, trust_steam_id=True,
                             env={'NEBULA_PROTECTED_ACCOUNTS': OTHER, 'NEBULA_PROTECT_STAFF_ACCOUNTS': '0'})
        self.refused(relaxed, OTHER)
        self.assertFalse(relaxed.register(self.payload(ACCOUNT), PEER)['created'])

    def test_new_protected_id_can_still_be_created_once(self):
        registration = Enrollment(self.store, self.authority, trust_steam_id=True,
                                  env={'NEBULA_PROTECTED_ACCOUNTS': ACCOUNT})
        self.assertTrue(registration.register(self.payload(ACCOUNT), PEER)['created'])
        self.refused(registration, ACCOUNT)


class OperatorLimits(unittest.TestCase):
    setUp = fixture.EnrollmentPolicy.setUp
    tearDown = fixture.EnrollmentPolicy.tearDown
    payload = fixture.EnrollmentPolicy.payload

    def test_environment_sets_cap_and_rate_limits_with_policy_defaults(self):
        strict = Enrollment(self.store, self.authority, env={})
        self.assertEqual((strict.maximum, strict.per_ip, strict.global_hourly), (1000, 8, 100))
        trusted = Enrollment(self.store, self.authority, trust_steam_id=True, env={
            'NEBULA_ENROLLMENT_PER_IP_HOURLY': '', 'NEBULA_ENROLLMENT_GLOBAL_HOURLY': ''})
        self.assertEqual((trusted.per_ip, trusted.global_hourly), (120, 1200))
        configured = Enrollment(self.store, self.authority, clock=lambda: self.now, env={
            'NEBULA_ENROLLMENT_MAX_ACCOUNTS': '1', 'NEBULA_ENROLLMENT_PER_IP_HOURLY': '3',
            'NEBULA_ENROLLMENT_GLOBAL_HOURLY': '50'})
        self.assertEqual((configured.maximum, configured.per_ip, configured.global_hourly), (1, 3, 50))
        self.assertTrue(configured.register(self.payload(), PEER)['created'])
        with self.assertRaises(EnrollmentError) as caught:
            configured.register(self.payload(OTHER, secrets.token_urlsafe(32)), PEER)
        self.assertEqual(caught.exception.code, 'registration_capacity_reached')
        for expected in ('registration_capacity_reached', 'registration_rate_limited'):  # Attempts 3 and 4.
            with self.assertRaises(EnrollmentError) as caught:
                configured.register(self.payload(THIRD, secrets.token_urlsafe(32)), PEER)
            self.assertEqual(caught.exception.code, expected)
        # Explicit constructor arguments still win over the environment.
        self.assertEqual(Enrollment(self.store, self.authority, maximum=7,
                                    env={'NEBULA_ENROLLMENT_MAX_ACCOUNTS': '1'}).maximum, 7)

    def test_invalid_operator_values_are_refused(self):
        for env in ({'NEBULA_ENROLLMENT_MAX_ACCOUNTS': '-1'}, {'NEBULA_ENROLLMENT_PER_IP_HOURLY': '0'},
                    {'NEBULA_PROTECTED_ACCOUNTS': '123,not-an-id'}, {'NEBULA_PROTECT_STAFF_ACCOUNTS': 'yes'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                enrollment_policy(env)
        self.assertEqual(enrollment_policy({'NEBULA_PROTECTED_ACCOUNTS': f' {ACCOUNT} ,{OTHER}'})['protected_accounts'],
                         frozenset({ACCOUNT, OTHER}))


if __name__ == '__main__': unittest.main()
