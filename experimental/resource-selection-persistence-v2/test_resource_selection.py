"""Temporary databases/files only. No listeners, processes or active state."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(HERE / 'backend'))
from state import Store
from resources import ResourceCatalog, ResourceEntitlements
from resource_selection import SelectionAuthority

PET = 'A0IQgRXmw2UMG8T5UGrVE022o7Id25GU'
LOCO = 'AJ7C1vNaTXDE2G5xRD5Uq4Tqv22a775K'


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nebula-selection-offline-')
        self.root = Path(self.temp.name)
        self.open()
        self.resources.grant('preservation-offline-test', 'companions', PET)
        self.resources.grant('preservation-offline-test', 'locomotions', LOCO)
        self.guid = '1' * 32
        self.lease('scene-one')
        with self.store.db:
            self.store.db.execute('INSERT INTO sessions VALUES(?,?,?)', (self.guid, 'preservation-offline-test', 1))
            self.store.db.execute('INSERT INTO allocations VALUES(?,?,?,?,?,?)', (self.guid, 'scene-one', 'Nexus', '127.0.0.1', 28000, 1))

    def lease(self, instance, owner='a'*32):
        folder = self.root / 'instances' / instance
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'instance-status.json').write_text(json.dumps(dict(instance_id=instance, owner=owner, psidglobal='Home' if instance == 'scene-two' else 'Nexus',
            listening=True, listener_bound=True, heartbeat=time.time())))

    def open(self):
        self.store = Store(self.root / 'preservation.sqlite3')
        self.resources = ResourceEntitlements(self.store, ResourceCatalog(ROOT / 'protocol'))
        self.authority = SelectionAuthority(self.store, self.resources)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def request(self, kind='companions', item=PET, revision=0):
        now = time.time()
        return dict(format_version=1, request_id=uuid.uuid4().hex, guid=self.guid, instance_id='scene-one', instance_owner='a'*32,
                    kind=kind, item_id=item, expected_revision=revision, created_at=now, expires_at=now+15)

    def test_select_restart_new_session_and_scene(self):
        self.assertEqual('committed', self.authority.process(self.request(), 'scene-one')['status'])
        self.store.close()
        self.open()
        self.assertEqual(PET, self.authority.snapshot('preservation-offline-test')['selected_companion'])
        old = self.request()
        with self.store.db:
            self.store.db.execute('INSERT INTO sessions VALUES(?,?,?)', ('2'*32, 'preservation-offline-test', 2))
            self.store.db.execute('INSERT INTO allocations VALUES(?,?,?,?,?,?)', ('2'*32, 'scene-two', 'Home', '127.0.0.1', 28001, 2))
        self.assertEqual('rejected', self.authority.process(old, 'scene-one')['status'])
        self.guid = '2'*32
        request = self.request(item='', revision=1)
        request['instance_id'] = 'scene-two'
        self.lease('scene-two')
        self.assertEqual('committed', self.authority.process(request, 'scene-two')['status'])
        self.assertEqual('', self.authority.snapshot('preservation-offline-test')['selected_companion'])

    def test_revoke_clears_and_regrant_does_not_reequip(self):
        self.authority.process(self.request(), 'scene-one')
        with self.store.db:
            self.store.db.execute('DELETE FROM resource_entitlements WHERE kind=?', ('companions',))
        self.assertEqual('', self.authority.snapshot('preservation-offline-test')['selected_companion'])
        self.resources.grant('preservation-offline-test', 'companions', PET)
        self.assertEqual(2, self.authority.snapshot('preservation-offline-test')['companion_revision'])
        self.assertEqual('', self.authority.selected('preservation-offline-test', 'companions')[0])

    def test_not_owned_or_cross_kind_rejected(self):
        for request in (self.request(item=LOCO), self.request(kind='locomotions', item=PET)):
            self.assertEqual('resource_not_owned', self.authority.process(request, 'scene-one')['reason'])
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM resource_selections').fetchone()[0])

    def test_current_allocation_rechecked(self):
        request = self.request()
        with self.store.db:
            self.store.db.execute("UPDATE allocations SET instance_id='scene-two'")
        self.assertEqual('rejected', self.authority.process(request, 'scene-one')['status'])

    def test_revision_serializes_requests(self):
        first, second = self.request(), self.request(item='')
        self.assertEqual('committed', self.authority.process(first, 'scene-one')['status'])
        self.assertEqual('revision_conflict', self.authority.process(second, 'scene-one')['reason'])

    def test_old_instance_process_lease_rejected(self):
        request = self.request()
        self.lease('scene-one', owner='b'*32)
        self.assertEqual('instance_lease_not_current', self.authority.process(request, 'scene-one')['reason'])
        self.assertEqual(('', 0), self.authority.selected('preservation-offline-test', 'companions'))

    def test_duplicate_receipt_and_conflicting_payload(self):
        request = self.request()
        ack = self.authority.process(request, 'scene-one')
        self.assertEqual(ack, self.authority.process(request, 'scene-one'))
        request['item_id'] = ''
        with self.assertRaises(ValueError):
            self.authority.process(request, 'scene-one')
        self.assertEqual(1, self.authority.selected('preservation-offline-test', 'companions')[1])

    def test_receipt_failure_rolls_back_selection(self):
        with self.store.db:
            self.store.db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON resource_selection_receipts BEGIN SELECT RAISE(ABORT,'offline failure'); END")
        with self.assertRaises(Exception):
            self.authority.process(self.request(), 'scene-one')
        self.assertEqual(('', 0), self.authority.selected('preservation-offline-test', 'companions'))

    def test_symlink_request_not_followed(self):
        folder = self.root / 'instances/scene-one/resource-selections'
        folder.mkdir()
        request = self.request()
        outside = self.root / 'outside.json'
        outside.write_text(json.dumps(request))
        (folder / (request['request_id']+'.request.json')).symlink_to(outside)
        self.authority.pump(self.root)
        self.assertEqual(('', 0), self.authority.selected('preservation-offline-test', 'companions'))

    def test_unexpected_catalog_failure_does_not_erase_selection(self):
        self.authority.process(self.request(), 'scene-one')
        original = self.resources.catalog.resolve
        self.resources.catalog.resolve = lambda *args: (_ for _ in ()).throw(RuntimeError('temporary catalog failure'))
        with self.assertRaises(RuntimeError):
            self.authority.snapshot('preservation-offline-test')
        self.resources.catalog.resolve = original
        self.assertEqual((PET, 1), self.authority.selected('preservation-offline-test', 'companions'))

    def test_clock_expiry_future_and_malformed(self):
        for delta in (-16, 1):
            request = self.request()
            self.assertEqual('rejected', self.authority.process(request, 'scene-one', now=request['created_at']-delta)['status'])
        request = self.request()
        request['expected_revision'] = True
        with self.assertRaises(ValueError):
            self.authority.process(request, 'scene-one')

    def test_ack_failure_recovers_after_restart_without_second_commit(self):
        request = self.request()
        folder = self.root / 'instances/scene-one/resource-selections'
        folder.mkdir(parents=True)
        (folder / (request['request_id']+'.request.json')).write_text(json.dumps(request))
        original = self.store._publish_snapshot
        self.store._publish_snapshot = lambda *args: (_ for _ in ()).throw(OSError('simulated crash after commit'))
        self.authority.pump(self.root)
        self.assertEqual(1, self.authority.selected('preservation-offline-test', 'companions')[1])
        self.store._publish_snapshot = original
        self.store.close()
        self.open()
        self.authority.pump(self.root)
        ack = json.loads((folder / (request['request_id']+'.ack.json')).read_text())
        self.assertEqual('committed', ack['status'])
        self.assertEqual(1, ack['revision'])

    def test_both_kinds_preserve_every_existing_table_and_idempotent_migration(self):
        def other_tables():
            return {name: [tuple(row) for row in self.store.db.execute('SELECT * FROM '+name)]
                    for (name,) in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    if not name.startswith('resource_selection')}
        before = other_tables()
        self.authority.process(self.request(), 'scene-one')
        self.authority.process(self.request(kind='locomotions', item=LOCO), 'scene-one')
        SelectionAuthority(self.store, self.resources)
        self.assertEqual(before, other_tables())
        self.assertEqual(LOCO, self.authority.snapshot('preservation-offline-test')['selected_locomotion'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
