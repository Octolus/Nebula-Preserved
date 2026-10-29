"""Offline fault checks for nested grants sharing a durable transaction."""
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from state import Store
from wire import ProtocolError

class AtomicStore(unittest.TestCase):
    def setUp(self):
        self.sockets = patch.object(socket, 'socket', side_effect=AssertionError('No sockets'))
        self.sockets.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests")/'work/offline-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.path = Path(self.temp.name)/'state.sqlite3'
        self.store = Store(self.path)
        self.store.account('A')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.sockets.stop()

    def names(self):
        return {row[0]:row[1] for row in self.store.db.execute('SELECT ps4_id,username FROM profiles')}

    def test_grant_helper_commit_does_not_escape_failure_group(self):
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with self.store.atomic():
                self.store.account('A', 'changed')
                self.store.account('B')
                self.store.db.commit()
                raise RuntimeError('injected')
        self.assertEqual(self.names(), {'A':'A'})
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.names(), {'A':'A'})

    def test_success_commits_all_nested_helpers(self):
        with self.store.atomic():
            self.store.account('A', 'changed')
            with self.store.atomic():
                self.store.account('B')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.names(), {'A':'changed','B':'B'})

    def test_caught_child_context_error_aborts_whole_group(self):
        with self.assertRaises(ProtocolError):
            with self.store.atomic():
                self.store.account('B')
                try:
                    with self.store.db:
                        self.store.db.execute('INSERT INTO profiles VALUES(?,?,?,?,?)', ('A','bad','PS4','MALE',0))
                except sqlite3.IntegrityError:
                    pass
                self.store.account('C')
        self.assertEqual(self.names(), {'A':'A'})

    def test_schema_script_is_rejected_before_implicit_commit(self):
        with self.assertRaises(RuntimeError):
            with self.store.atomic():
                self.store.account('B')
                self.store.db.executescript('CREATE TABLE should_not_exist(x);')
        self.assertEqual(self.names(), {'A':'A'})
        self.assertIsNone(self.store.db.execute("SELECT name FROM sqlite_master WHERE name='should_not_exist'").fetchone())

    def test_explicit_rollback_aborts_group(self):
        with self.assertRaises(ProtocolError):
            with self.store.atomic():
                self.store.account('B')
                self.store.db.rollback()
        self.assertEqual(self.names(), {'A':'A'})

    def test_other_connection_cannot_write_during_group(self):
        other = sqlite3.connect(self.path, timeout=0)
        try:
            with self.store.atomic():
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute("UPDATE profiles SET username='other' WHERE ps4_id='A'")
                self.store.account('A', 'group')
            self.assertEqual(self.names()['A'], 'group')
        finally:
            other.close()

    def test_identity_and_inbound_relations_rollback_together(self):
        self.store.account('A', 'Alice')
        self.store.account('B', 'Bob')
        self.store.accept_friendship('A', 'B')
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO relations VALUES(?,?,?,'favorite')",
                ('A', 'Bob', 'StandaloneWindows'),
            )

        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with self.store.atomic():
                self.store.account('B', 'Robert')
                raise RuntimeError('injected')

        self.assertEqual(self.names(), {'A': 'Alice', 'B': 'Bob'})
        self.assertEqual(
            self.store.relation_kinds('A', 'Bob', 'StandaloneWindows'),
            {'friend', 'favorite'},
        )
        self.assertEqual(self.store.relation_kinds('A', 'Robert', 'StandaloneWindows'), set())
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.names(), {'A': 'Alice', 'B': 'Bob'})
        self.assertEqual(
            self.store.relation_kinds('A', 'Bob', 'StandaloneWindows'),
            {'friend', 'favorite'},
        )

if __name__ == '__main__': unittest.main()

