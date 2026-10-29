"""Independent read-only gateway-policy checks over disposable Store data only."""
from pathlib import Path
import hashlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from management import Management
from public_access import migrate
from remote_gateway import Authority, Denied
from service import Service
from state import Store, Catalog

ACCOUNT = 'gateway-review-fake-account'
GUID = 'a' * 32
PORT = 40120
ACTOR = {'id': 'owner', 'role': 'owner'}
TOKEN = b'disposable-review-management-token-123456789'


class Review(unittest.TestCase):
    def setUp(self):
        for owner, name in ((socket.socket, 'connect'), (socket.socket, 'bind'), (subprocess, 'Popen')):
            self.enterContext(patch.object(owner, name, side_effect=AssertionError('No network or child process in gateway tests')))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'preservation.sqlite3')
        self.addCleanup(self.store.close)
        self.store.account(ACCOUNT, 'GatewayReviewFake')
        self.store.bind_session(ACCOUNT, GUID)
        migrate(self.store.db)
        with self.store.db:
            self.store.db.execute('INSERT INTO public_access_credentials VALUES(?,?,?,?,?,?,NULL)',
                (ACCOUNT, b's' * 16, b'v' * 32, None, None, time.time()))
        self.allocation(GUID)
        self.authority = Authority(self.root, PORT, PORT)
        class Directory:
            def all_ready(self):
                return [{'instance_id': 'review-instance', 'psidglobal': 'Nexus',
                         'ip': '127.0.0.1', 'bind': '127.0.0.1', 'port': PORT,
                         'heartbeat': time.time()}]
        self.authority.instances = Directory()
        self.expected = self.binding(GUID)
        self.assertEqual(self.resolve(), self.expected)

    def allocation(self, guid):
        with self.store.db:
            self.store.db.execute('INSERT INTO allocations VALUES(?,?,?,?,?,?)',
                (guid, 'review-instance', 'Nexus', '127.0.0.1', PORT, time.time()))

    def binding(self, guid):
        return {'account': ACCOUNT, 'guid': guid, 'instance': 'review-instance',
                'scene': 'Nexus', 'credential': hashlib.sha256(b's' * 16 + b'v' * 32).hexdigest()}

    def resolve(self):
        return self.authority.resolve(PORT, expected=self.expected)

    def test_committed_ban_and_unban_keep_old_gateway_session_revoked(self):
        with self.store.atomic():
            self.store.moderation.ban(ACCOUNT, reason='Review', actor=ACTOR, request_id='1' * 32)
        with self.assertRaisesRegex(Denied, 'banned'): self.resolve()
        with self.store.atomic():
            self.store.moderation.unban(ACCOUNT, reason='Review', actor=ACTOR, request_id='2' * 32)
        with self.assertRaisesRegex(Denied, 'revoked_session'): self.resolve()

    def test_committed_kick_does_not_wait_for_scene_snapshot(self):
        with self.store.atomic():
            self.store.moderation.kick(ACCOUNT, reason='Review', actor=ACTOR, request_id='3' * 32)
        with self.assertRaisesRegex(Denied, 'revoked_session'): self.resolve()
        fresh = 'b' * 32
        self.store.bind_session(ACCOUNT, fresh)
        self.allocation(fresh)
        self.expected = self.binding(fresh)
        self.assertEqual(self.resolve(), self.expected)

    def test_missing_moderation_authority_fails_closed(self):
        with self.store.db: self.store.db.execute('DROP TABLE moderation_accounts')
        with self.assertRaisesRegex(Denied, 'moderation_unavailable'): self.resolve()

    def test_credential_revocation_still_enforced(self):
        with self.store.db:
            self.store.db.execute('UPDATE public_access_credentials SET revoked_at=1 WHERE ps4_id=?', (ACCOUNT,))
        with self.assertRaisesRegex(Denied, 'credential'): self.resolve()

    def test_replaying_kick_receipt_does_not_revoke_fresh_session(self):
        service = Service(self.store, Catalog(ROOT / 'protocol'))
        manager = Management(self.store, service, TOKEN, [{'id': 'owner', 'role': 'owner', 'enabled': True}])
        headers = {'Authorization': 'Bearer ' + TOKEN.decode(), 'X-Management-Actor': 'owner',
                   'Idempotency-Key': 'review-stable-kick-key'}
        path = 'users/' + ACCOUNT + '/kick'
        first = manager.command(path, {'reason': 'Review'}, headers)
        fresh = 'c' * 32
        self.store.bind_session(ACCOUNT, fresh)
        self.allocation(fresh)
        replay = manager.command(path, {'reason': 'Review'}, headers)
        self.assertEqual(first['request_id'], replay['request_id'])
        self.assertTrue(replay['replayed'])
        self.expected = self.binding(fresh)
        self.assertEqual(self.resolve(), self.expected)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM moderation_events').fetchone()[0], 1)


if __name__ == '__main__':
    def forbidden(*args, **kwargs):
        raise AssertionError('Review prohibits sockets and child processes')
    with patch.object(socket.socket, 'connect', forbidden), patch.object(socket.socket, 'bind', forbidden), \
         patch.object(subprocess, 'Popen', forbidden):
        unittest.main(verbosity=2)
