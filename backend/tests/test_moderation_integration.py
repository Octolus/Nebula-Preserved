"""Real management transactions and native HTTP grammars over disposable state."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE/'backend'), str(BASE/'tools')]
from management import Management, ManagementError
from moderation import report_id
from public_access import AccessDenied, actor_scope
from service import Service
from state import Store, Catalog
from wire import ProtocolError, session_guid

ACCOUNT, OTHER = 'moderation-player-one', 'moderation-player-two'
TOKEN = b'temporary-moderation-test-service-token-12345'


class ModerationIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'preservation.sqlite3')
        self.addCleanup(self.store.close)
        self.service = Service(self.store, Catalog(BASE/'protocol'))
        self.store.account(ACCOUNT, 'TestPlayerOne')
        self.store.account(OTHER, 'TestPlayerTwo')
        self.guid = session_guid(ACCOUNT, 'a'*64)
        self.other_guid = session_guid(OTHER, 'b'*64)
        self.store.bind_session(ACCOUNT, self.guid)
        self.store.bind_session(OTHER, self.other_guid)
        self.manager = Management(self.store, self.service, TOKEN,
            [{'id': role, 'role': role, 'enabled': True} for role in ('owner', 'admin', 'moderator')])
        self.sequence = 0

    def headers(self, actor='owner', key=None):
        self.sequence += 1
        return {'Authorization': 'Bearer '+TOKEN.decode(), 'X-Management-Actor': actor,
                'Idempotency-Key': key or 'moderation-integration-'+str(self.sequence)}

    def command(self, action, body=None, actor='owner', key=None):
        return self.manager.command(action, {'reason': 'Disposable integration test', **(body or {})}, self.headers(actor, key))

    def player(self, action, body=None, **kwargs):
        return self.command('users/'+ACCOUNT+'/'+action, body, **kwargs)

    def wire(self, route, *fields):
        return self.service.dispatch(route, '#'.join([*fields, 'StandaloneWindows']))

    def read(self, route, actor='owner'):
        return self.manager.read(route, {}, self.manager.actor(self.headers(actor)))

    def test_permanent_ban_native_bootstrap_and_checker_actor_binding(self):
        self.player('ban', actor='moderator')
        reply = self.wire('N2UserExist', 'TestPlayerOne', '1', 'True', ACCOUNT, 'nonce').split('#')
        self.assertEqual(reply, [ACCOUNT, '', 'preservation', 'false', 'true', 'null', 'Disposable integration test'])
        self.assertEqual(self.wire('UserExistsServlet', ACCOUNT, '1', 'False', ACCOUNT, 'n').split('#')[4:6], ['true','null'])
        # Authenticated actor wins over claimed persona/MAC/BSSID telemetry.
        with actor_scope(ACCOUNT):
            self.assertEqual(self.wire('CheckerServlet', 'TestPlayerTwo', 'ignored', 'ignored', 'nonce').split('#')[1:4], ['nonce','true','null'])
        with actor_scope(OTHER):
            self.assertEqual(self.wire('CheckerServlet', 'TestPlayerOne', 'ignored', 'ignored', 'n').split('#')[2], 'false')
            with self.assertRaises(AccessDenied):
                self.wire('N2UserExist', 'TestPlayerOne', '1', 'True', ACCOUNT, 'n')

    def test_timed_ban_readable_utc_and_existing_load_ban_branch(self):
        self.player('ban', {'expires_at': int(time.time())+3600})
        fields = self.wire('N2UserExist', 'TestPlayerOne', '1', 'False', ACCOUNT, 'n').split('#')
        self.assertTrue(fields[5].endswith(' UTC'))
        self.assertEqual(self.wire('N2LoadSpace', self.guid, ACCOUNT, 'Nexus', 'false', '', ''), self.guid+'#true#false')
        with self.assertRaises(ProtocolError):
            self.store.session(self.guid, ACCOUNT)

    def test_unban_and_fresh_login_do_not_resurrect_previous_guid(self):
        self.player('ban')
        self.player('unban')
        with self.assertRaises(ProtocolError):
            self.store.bind_session(ACCOUNT, self.guid)
        self.assertIsNone(self.store.current_guid(ACCOUNT))
        self.assertEqual(self.wire('ChannelGUIDServlet', ACCOUNT, 'c'*64), 'true#')
        self.assertEqual(self.store.current_guid(ACCOUNT), session_guid(ACCOUNT, 'c'*64))

    def test_kick_preserves_wallet_and_other_account_and_replay(self):
        self.service.shop.set_wallet(ACCOUNT, 53, 17, 2)
        before = self.service.shop.wallet(ACCOUNT)
        result = self.player('kick', actor='moderator', key='same-kick-request')
        replay = self.player('kick', actor='moderator', key='same-kick-request')
        self.assertEqual(result['request_id'], replay['request_id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], 1)
        self.assertEqual(self.service.shop.wallet(ACCOUNT), before)
        self.assertEqual(self.store.session(self.other_guid)['ps4_id'], OTHER)
        with self.assertRaises(ProtocolError): self.store.session(self.guid)

    def test_all_policy_history_and_revocation_rollback_with_management_audit(self):
        self.store.db.execute("CREATE TRIGGER integration_audit_failure BEFORE INSERT ON management_audit BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.player('ban')
        self.assertFalse(self.service.moderation.status(ACCOUNT)['banned'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_revoked_sessions').fetchone()[0], 0)
        self.assertEqual(self.store.session(self.guid)['ps4_id'], ACCOUNT)

    def test_permission_boundaries_and_staff_label_is_not_power(self):
        for actor in ('admin','moderator'):
            with self.assertRaises(ManagementError): self.player('staff-label', {'label':'Moderator'}, actor=actor)
        self.player('staff-label', {'label':'Moderator'})
        label = self.wire('PlayerLabelInfoServlet', self.other_guid, OTHER, self.guid).split('#')
        self.assertEqual(label[5], 'Moderator')
        self.assertEqual(self.service.moderation.status(ACCOUNT)['role'], 'player')
        self.assertFalse(self.read('capabilities')['game_privilege_mutation_supported'])
        with actor_scope(ACCOUNT):
            with self.assertRaises(ManagementError): self.player('ban')
        with self.assertRaises(ManagementError): self.player('wallet-adjustments', {'currency':'crystals','delta':1}, actor='moderator')

    def test_maintenance_and_news_use_existing_native_consumers(self):
        with self.assertRaises(ManagementError): self.command('moderation/maintenance', {'minutes':3}, actor='moderator')
        self.command('moderation/maintenance', {'minutes':3}, actor='admin')
        self.assertEqual(self.wire('checkerToServerDownMaintenanceServlet', self.guid, ACCOUNT), 'true#'+self.guid+'#'+ACCOUNT+'#3')
        # A countdown is a message, not an implicit account-access shutdown.
        self.assertEqual(self.store.session(self.guid)['ps4_id'], ACCOUNT)
        published = self.command('moderation/news', {'text':'Scheduled preservation update'}, actor='admin')
        news = self.wire('GetNewsServlet', '12').split('#')
        self.assertEqual(news[0], '1');self.assertEqual(news[2], 'Scheduled preservation update')
        self.assertFalse(self.read('capabilities')['announcement_supported'])
        identity = published['after']['news_id']
        self.command('moderation/news/'+identity+'/archive', actor='admin')
        self.assertIn('Original online news is unavailable.', self.wire('GetNewsServlet','12'))

    def test_reports_keep_target_separate_from_reporter_and_audit_reviews(self):
        self.assertEqual(self.wire('ReportServlet', self.guid, ACCOUNT, '0', 'ReportedName', 'Report text').split('#')[3], 'true')
        self.assertEqual(self.wire('ReportServlet', self.guid, ACCOUNT, '0', 'ReportedName', 'Second text').split('#')[3], 'false')
        listed = self.read('moderation/reports')['items']
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['target'], 'ReportedName')
        self.assertEqual(listed[0]['reporter_account_id'], ACCOUNT)
        self.assertEqual(listed[0]['text'], 'Report text')
        identity = report_id(self.guid, 'ReportedName', 0)
        self.command('moderation/reports/'+identity, {'status':'resolved','note':'Reviewed'}, actor='moderator')
        self.assertEqual(self.read('moderation/reports')['items'][0]['status'], 'resolved')
        self.assertFalse(self.service.moderation.status(ACCOUNT)['banned'])
        self.assertEqual(self.read('moderation/events')['items'][0]['operation'], 'report.review')

    def test_failed_snapshot_dispatch_replay_retries_after_committed_policy(self):
        calls=[]
        def publish():
            calls.append(True)
            if len(calls)==1: raise OSError('temporary replace failure')
        self.service.publish_runtime_state=publish
        first=self.player('mute', key='stable-dispatch-key')
        self.assertEqual(first['runtime_sync'], 'pending')
        self.assertTrue(self.service.moderation.status(ACCOUNT)['muted'])
        replay=self.player('mute', key='stable-dispatch-key')
        self.assertEqual(replay['runtime_sync'], 'snapshot_published')
        self.assertEqual(first['request_id'],replay['request_id'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0],1)

    def test_explicit_account_operator_link_protects_equal_and_higher_roles(self):
        self.command('operators/linked-administrator', {'role':'admin','enabled':True})
        self.command('operators/linked-administrator/player-link', {'account_id':ACCOUNT})
        for actor in ('moderator','admin'):
            with self.assertRaises(ManagementError): self.player('ban', actor=actor)
            with self.assertRaises(ManagementError): self.player('kick', actor=actor)
            with self.assertRaises(ManagementError): self.player('mute', actor=actor)
        self.assertFalse(self.service.moderation.status(ACCOUNT)['banned'])
        self.player('ban', actor='owner')
        self.assertTrue(self.service.moderation.status(ACCOUNT)['banned'])


if __name__ == '__main__': unittest.main()
