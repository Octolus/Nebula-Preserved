"""Role matrices, transaction faults and concurrent retries on disposable state."""
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tools')]
from management import Management, ManagementError
from moderation import report_id
from service import Service
from state import Catalog, Store
from test_moderation_edges import snapshot

ACCOUNT, OTHER = 'edge-management-player', 'edge-management-other'
TOKEN = b'disposable-management-edge-test-token-12345'
OPERATORS = [{'id': role, 'role': role, 'enabled': True}
             for role in ('owner', 'admin', 'moderator')]


class ManagementEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / 'protocol')

    def setUp(self):
        for method in ('connect', 'connect_ex', 'bind'):
            self.enterContext(patch.object(socket.socket, method,
                side_effect=AssertionError('Management unit tests must stay offline')))
        self.temp = tempfile.TemporaryDirectory(prefix='nebula-management-edges-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite3'
        self.store = Store(Path(':memory:'))
        self.addCleanup(self.store.close)
        self.service = Service(self.store, self.catalog)
        self.store.account(ACCOUNT, 'ManagementEdgePlayer')
        self.store.account(OTHER, 'OtherEdgePlayer')
        self.sequence = self.session_sequence = 0
        self.fresh_session()
        self.service.shop.set_wallet(ACCOUNT, 100, 20, 0)
        self.manager = Management(self.store, self.service, TOKEN, OPERATORS)

    def fresh_session(self):
        self.session_sequence += 1
        self.guid = f'{self.session_sequence:032x}'
        with patch('state.time.time', return_value=1000.0 + self.session_sequence):
            self.store.bind_session(ACCOUNT, self.guid)

    def headers(self, actor='owner', key=None):
        self.sequence += 1
        return {'Authorization': 'Bearer ' + TOKEN.decode(), 'X-Management-Actor': actor,
                'Idempotency-Key': key or f'edge-request-{self.sequence:06d}'}

    def command(self, route, body=None, actor='owner', key=None):
        return self.manager.command(route, {'reason': 'Disposable edge test', **(body or {})},
                                    self.headers(actor, key))

    def player(self, action, **kwargs):
        return self.command('users/' + ACCOUNT + '/' + action, **kwargs)

    def test_all_role_pairs_and_all_five_actions_respect_explicit_player_links(self):
        ranks = {'moderator': 1, 'admin': 2, 'owner': 3}
        for target_role in ranks:
            self.command('operators/linked-operator', {'role': target_role, 'enabled': True})
            self.command('operators/linked-operator/player-link', {'account_id': ACCOUNT})
            for actor in ranks:
                for action in ('ban', 'unban', 'kick', 'mute', 'unmute'):
                    with self.subTest(target=target_role, actor=actor, action=action):
                        allowed = actor == 'owner' or ranks[actor] > ranks[target_role]
                        before = snapshot(self.store.db)
                        if not allowed:
                            with self.assertRaises(ManagementError) as got:
                                self.player(action, actor=actor)
                            self.assertEqual(got.exception.status, 403)
                            self.assertEqual(snapshot(self.store.db), before)
                        else:
                            result = self.player(action, actor=actor)
                            self.assertFalse(result['replayed'])
                            self.player('unban')
                            self.player('unmute')
                            self.fresh_session()

    def test_disabled_link_does_not_grant_hierarchy_or_block_moderation(self):
        self.command('operators/disabled-owner', {'role': 'owner', 'enabled': False})
        self.command('operators/disabled-owner/player-link', {'account_id': ACCOUNT})
        self.player('ban', actor='moderator')
        self.assertTrue(self.store.moderation.status(ACCOUNT)['banned'])
        with self.assertRaises(ManagementError) as got:
            self.manager.actor(self.headers('disabled-owner'))
        self.assertEqual(got.exception.status, 403)

    def test_duplicate_player_link_is_atomic_and_unlink_requires_explicit_null(self):
        self.command('operators/admin/player-link', {'account_id': ACCOUNT})
        for route, body, status in (
            ('operators/moderator/player-link', {'account_id': ACCOUNT}, 409),
            ('operators/admin/player-link', {}, 400),
            ('operators/admin/player-link', {'account_id': 'missing-player'}, 404),
            ('operators/missing-operator/player-link', {'account_id': OTHER}, 404),
        ):
            with self.subTest(route=route, body=body):
                before = snapshot(self.store.db)
                with self.assertRaises(ManagementError) as got:
                    self.command(route, body)
                self.assertEqual(got.exception.status, status)
                self.assertEqual(snapshot(self.store.db), before)
        self.command('operators/admin/player-link', {'account_id': None})
        self.player('ban', actor='moderator')
        self.assertTrue(self.store.moderation.status(ACCOUNT)['banned'])

    def test_final_audit_failure_rolls_back_every_compound_mutation(self):
        with self.store.atomic():
            self.store.moderation.record_report(self.guid, 'ReportedPlayer', 0, 'Details')
        report = report_id(self.guid, 'ReportedPlayer', 0)
        news = self.command('moderation/news', {'text': 'Existing news'})['after']['news_id']
        cases = [
            ('users/' + ACCOUNT + '/' + action, {})
            for action in ('ban', 'unban', 'kick', 'mute', 'unmute')
        ] + [
            ('users/' + ACCOUNT + '/staff-label', {'label': 'Staff'}),
            ('users/' + ACCOUNT + '/wallet-adjustments', {'currency': 'np', 'delta': 1}),
            ('operators/moderator/player-link', {'account_id': ACCOUNT}),
            ('operators/moderator', {'role': 'admin', 'enabled': True}),
            ('moderation/maintenance', {'minutes': 5}),
            ('moderation/reports/' + report, {'status': 'resolved', 'note': 'Review'}),
            ('moderation/news', {'text': 'Must roll back'}),
            ('moderation/news/' + news + '/archive', {}),
        ]
        for route, body in cases:
            with self.subTest(route=route):
                before = snapshot(self.store.db)
                with patch.object(self.manager, '_audit', side_effect=sqlite3.IntegrityError('Injected final audit failure')):
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.command(route, body)
                self.assertEqual(snapshot(self.store.db), before)

    def test_idempotency_conflicts_cannot_change_route_target_or_policy(self):
        self.player('mute', key='same-edge-request')
        for route, body in (
            ('users/' + ACCOUNT + '/ban', {}),
            ('users/' + OTHER + '/mute', {}),
            ('users/' + ACCOUNT + '/mute', {'reason': 'Changed reason'}),
            ('users/' + ACCOUNT + '/mute', {'expires_at': None}),
        ):
            with self.subTest(route=route, body=body):
                before = snapshot(self.store.db)
                with self.assertRaises(ManagementError) as got:
                    self.command(route, body, key='same-edge-request')
                self.assertEqual(got.exception.status, 409)
                self.assertEqual(snapshot(self.store.db), before)

    def test_idempotency_keys_are_scoped_to_the_authenticated_actor(self):
        first = self.player('mute', actor='owner', key='shared-edge-key')
        second = self.player('mute', actor='moderator', key='shared-edge-key')
        self.assertNotEqual(first['request_id'], second['request_id'])
        self.assertFalse(second['replayed'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], 2)

    def test_revocation_between_initial_check_and_write_lock_prevents_mutation(self):
        original = self.manager.actor
        calls = []
        def revoke_after_first_check(headers, permission='read'):
            actor = original(headers, permission)
            calls.append(actor)
            if len(calls) == 1:
                with self.store.db:
                    self.store.db.execute("UPDATE management_operators SET enabled=0 WHERE operator_id='moderator'")
            return actor
        events = self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0]
        with patch.object(self.manager, 'actor', side_effect=revoke_after_first_check):
            with self.assertRaises(ManagementError) as got:
                self.player('ban', actor='moderator')
        self.assertEqual(got.exception.status, 403)
        self.assertFalse(self.store.moderation.status(ACCOUNT)['banned'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], events)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM management_requests').fetchone()[0], 0)

    def test_concurrent_ban_retries_commit_one_policy_event_and_receipt(self):
        # Only this test needs disk and distinct SQLite connections. Keep the
        # permission/fault matrix in real in-memory SQLite for fast feedback.
        destination = sqlite3.connect(self.path)
        try:
            self.store.db.backup(destination)
        finally:
            destination.close()
        barrier = threading.Barrier(2)
        results, failures = [], []
        headers = self.headers('moderator', 'concurrent-edge-ban')
        body = {'reason': 'Concurrent duplicate moderation request'}
        def run():
            store = None
            try:
                store = Store(self.path)
                service = Service(store, self.catalog)
                manager = Management(store, service, TOKEN, OPERATORS)
                barrier.wait(timeout=10)
                results.append(manager.command('users/' + ACCOUNT + '/ban', body, headers))
            except BaseException as error:
                failures.append(error)
                barrier.abort()
            finally:
                if store is not None:
                    store.close()
        threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), 'Concurrent request did not finish')
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(result['replayed'] for result in results), 1)
        self.assertEqual(len({result['request_id'] for result in results}), 1)
        persisted = Store(self.path)
        try:
            self.assertTrue(persisted.moderation.status(ACCOUNT)['banned'])
            for table in ('moderation_events', 'moderation_revoked_sessions', 'management_requests'):
                self.assertEqual(persisted.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 1, table)
        finally:
            persisted.close()


if __name__ == '__main__':
    unittest.main()
