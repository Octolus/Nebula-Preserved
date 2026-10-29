"""Deterministic policy sequences and boundary checks; real in-memory SQLite."""
import itertools
from pathlib import Path
import random
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moderation import MAX_UTC, Moderation, report_id
from public_access import actor_scope
from state import Store
from wire import ProtocolError

ACCOUNT = 'edge-policy-player'
OWNER = {'id': 'test-owner', 'role': 'owner'}


def snapshot(db):
    return {name: sorted(map(tuple, db.execute('SELECT * FROM "' + name + '"')), key=repr)
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")
            if not name.startswith('sqlite_')}


class PolicyEdges(unittest.TestCase):
    def setUp(self):
        for method in ('connect', 'connect_ex', 'bind'):
            self.enterContext(patch.object(socket.socket, method,
                side_effect=AssertionError('Policy unit tests must stay offline')))
        self.store = Store(Path(':memory:'))
        self.addCleanup(self.store.close)
        self.now = 1000.0
        self.policy = Moderation(self.store, clock=lambda: self.now)
        self.store.moderation = self.policy
        self.store.account(ACCOUNT, 'PolicyEdgePlayer')
        self.sequence = 0
        self.guid = '1' * 32
        with patch('state.time.time', return_value=1000.0):
            self.store.bind_session(ACCOUNT, self.guid)

    def command(self, method, *args, **kwargs):
        self.sequence += 1
        with self.store.atomic():
            return getattr(self.policy, method)(*args, reason='Deterministic edge test',
                actor=OWNER, request_id=f'{self.sequence:032x}', **kwargs)

    def assert_denied_unchanged(self, status, call):
        before = snapshot(self.store.db)
        with self.assertRaises(ProtocolError) as got:
            call()
        self.assertEqual(got.exception.status, status)
        self.assertEqual(snapshot(self.store.db), before)

    def test_generated_policy_sequences_match_independent_session_model(self):
        # Fixed seed, no sleeps: exercise transitions together, not just isolated setters.
        rng = random.Random(40421)
        revoked, issued = set(), {self.guid}
        latest, ban_until, mute_until = self.guid, False, False
        commands = 0
        for index in range(160):
            action = rng.choice(('ban', 'unban', 'mute', 'unmute', 'kick', 'login', 'tick'))
            with self.subTest(step=index, action=action):
                banned = ban_until is None or (ban_until is not False and self.now < ban_until)
                if action in ('ban', 'mute'):
                    expiry = rng.choice((None, int(self.now) + 1, int(self.now) + 7))
                    self.command(action, ACCOUNT, expires_at=expiry)
                    commands += 1
                    if action == 'ban':
                        ban_until = expiry
                        revoked.update(issued)
                    else:
                        mute_until = expiry
                elif action in ('unban', 'unmute'):
                    self.command(action, ACCOUNT)
                    commands += 1
                    if action == 'unban':
                        ban_until = False
                    else:
                        mute_until = False
                elif action == 'kick':
                    self.command('kick', ACCOUNT)
                    commands += 1
                    revoked.add(latest)
                elif action == 'login':
                    new_guid = f'{index + 100:032x}'
                    if banned:
                        self.assert_denied_unchanged(403, lambda: self.store.bind_session(ACCOUNT, new_guid))
                    else:
                        # A controlled creation timestamp prevents same-tick ordering flakes.
                        with patch('state.time.time', return_value=2000.0 + index):
                            self.store.bind_session(ACCOUNT, new_guid)
                        issued.add(new_guid)
                        latest = new_guid
                else:
                    self.now += rng.choice((0.0, 1.0, 7.0))
                banned = ban_until is None or (ban_until is not False and self.now < ban_until)
                muted = mute_until is None or (mute_until is not False and self.now < mute_until)
                before_reads = snapshot(self.store.db)
                status = self.policy.status(ACCOUNT)
                self.assertEqual((status['banned'], status['muted']), (banned, muted))
                self.assertEqual(self.store.current_guid(ACCOUNT),
                    None if banned or latest in revoked else latest)
                self.assertEqual({r[0] for r in self.store.db.execute(
                    'SELECT guid FROM moderation_revoked_sessions')}, revoked)
                self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], commands)
                for guid in issued | {'f' * 32}:
                    if banned or guid in revoked:
                        with self.assertRaises(ProtocolError) as got:
                            self.policy.ensure_allowed(ACCOUNT, guid)
                        self.assertEqual(got.exception.status, 403)
                    else:
                        self.assertTrue(self.policy.ensure_allowed(ACCOUNT, guid))
                self.assertEqual(snapshot(self.store.db), before_reads)

    def test_expiry_type_and_range_matrix_is_atomic_for_bans_mutes_and_news(self):
        invalid = (True, False, -1, 0, 1000, 1001.0, '1001', [], {},
                   float('nan'), float('inf'), float('-inf'), MAX_UTC + 1)
        for method, expiry in itertools.product(('ban', 'mute', 'publish_news'), invalid):
            with self.subTest(method=method, expiry=repr(expiry)):
                arg = 'Login news' if method == 'publish_news' else ACCOUNT
                self.assert_denied_unchanged(400,
                    lambda: self.command(method, arg, expires_at=expiry))

    def test_all_unicode_control_categories_are_rejected_before_storage(self):
        for marker in ('#', '\x00', '\n', '\r', '\x7f', '\x85', '\u200b', '\u202e', '\ud800', '\ue000'):
            for method, args in (
                ('set_staff_label', (ACCOUNT, 'Staff' + marker)),
                ('publish_news', ('News' + marker,)),
            ):
                with self.subTest(method=method, marker=ascii(marker)):
                    self.assert_denied_unchanged(400, lambda: self.command(method, *args))

    def test_exact_content_boundaries_accept_unicode_and_reject_one_more_character(self):
        self.command('set_staff_label', ACCOUNT, '\u00e9' * 32)
        self.assertEqual(self.policy.status(ACCOUNT)['staff_label'], '\u00e9' * 32)
        self.assert_denied_unchanged(400, lambda: self.command('set_staff_label', ACCOUNT, '\u00e9' * 33))
        self.command('publish_news', '\U0001f680' * 1000)
        self.assertEqual(self.policy.news()[0]['text'], '\U0001f680' * 1000)
        self.assert_denied_unchanged(400, lambda: self.command('publish_news', '\U0001f680' * 1001))

    def test_player_context_cannot_use_any_operator_mutator(self):
        with self.store.atomic():
            self.policy.record_report(self.guid, 'ReportedPlayer', 0, 'Details')
        identity = report_id(self.guid, 'ReportedPlayer', 0)
        news_id = self.command('publish_news', 'Before context test')[1]['news_id']
        cases = (
            ('ban', (ACCOUNT,)), ('unban', (ACCOUNT,)), ('kick', (ACCOUNT,)),
            ('mute', (ACCOUNT,)), ('unmute', (ACCOUNT,)),
            ('set_staff_label', (ACCOUNT, 'Staff')), ('set_maintenance', (5,)),
            ('publish_news', ('Must not publish',)), ('archive_news', (news_id,)),
            ('review_report', (identity, 'resolved', 'Review')),
        )
        with actor_scope(ACCOUNT):
            for method, args in cases:
                with self.subTest(method=method):
                    self.assert_denied_unchanged(403, lambda: self.command(method, *args))

    def test_clock_failures_never_grant_admission_or_write_policy(self):
        self.command('ban', ACCOUNT)
        for now in (True, None, '1000', -0.1, float('nan'), float('inf'), MAX_UTC + 1):
            with self.subTest(now=repr(now)):
                self.now = now
                self.assert_denied_unchanged(503, lambda: self.policy.ensure_allowed(ACCOUNT, self.guid))
                self.assert_denied_unchanged(503, lambda: self.command('unban', ACCOUNT))

    def test_report_hashes_separate_category_target_and_unicode_without_normalization(self):
        self.assertEqual(report_id(self.guid, 'Target', 0), report_id(self.guid, 'Target', 0))
        identities = {report_id(self.guid, target, option)
                      for target, option in itertools.product(('Target', 'target', '\u00e9', 'e\u0301'), range(3))}
        self.assertEqual(len(identities), 12)


if __name__ == '__main__':
    unittest.main()
