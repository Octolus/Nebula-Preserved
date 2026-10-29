"""Offline notification persistence checks; socket construction is forbidden."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from notifications import NotificationOutbox, TICKS_EPOCH
from state import Store
from wire import ProtocolError


class Notifications(unittest.TestCase):
    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("Network forbidden"))
        self.no_network.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-notification-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "state.sqlite3")
        self.store.account("sender", "Actual Donor")
        self.store.account("recipient", "Actual Recipient", "PS4")
        self.store.bind_session("recipient", "recipient-guid")
        self.outbox = NotificationOutbox(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def gift(self, key="gift-one"):
        with self.store.atomic():
            return self.outbox.enqueue_gift("recipient", "sender", "Shipped Item", key)

    def ack(self, event_id):
        row = self.outbox.pending()[0]
        return {"format_version": 1, "event_id": event_id, "target_ps4_id": "recipient",
                "guid": "recipient-guid", "source_username": row["source_username"],
                "source_platform": row["source_platform"], "notification_type": row["notification_type"],
                "accepted_at": time.time()}

    def test_gift_offline_persistence_and_stable_deduplication(self):
        event_id = self.gift()
        self.assertEqual(event_id, self.gift())
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.outbox = NotificationOutbox(self.store)
        rows = self.outbox.pending("recipient")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source_username"], rows[0]["source_platform"], rows[0]["notification_type"],
                          rows[0]["arguments"]), ("Actual Donor", 1, 3, "Shipped Item"))
        self.assertGreater(rows[0]["ticks"], TICKS_EPOCH)
        self.assertEqual(len(event_id), 32)

    def test_enqueue_requires_existing_entitlement_transaction(self):
        with self.assertRaises(RuntimeError):
            self.outbox.enqueue_gift("recipient", "sender", "Item", "key")
        with self.store.atomic():
            with self.assertRaises(RuntimeError):
                NotificationOutbox(self.store)
        self.assertEqual(self.outbox.pending(), [])

    def test_grant_and_notice_roll_back_together_on_fault(self):
        self.store.db.execute("CREATE TABLE notification_test_grants(account TEXT PRIMARY KEY)")
        self.store.db.commit()
        with self.assertRaisesRegex(RuntimeError, "fault"):
            with self.store.atomic():
                self.store.db.execute("INSERT INTO notification_test_grants VALUES('recipient')")
                self.outbox.enqueue_gift("recipient", "sender", "Item", "transaction-key")
                raise RuntimeError("fault")
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.outbox = NotificationOutbox(self.store)
        self.assertEqual(self.outbox.pending(), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM notification_test_grants").fetchone()[0], 0)

    def test_reward_uses_actual_recipient_identity_and_empty_unread_arguments(self):
        with self.store.atomic():
            event_id = self.outbox.enqueue_reward("recipient", "reward:route:trigger")
        notice = self.outbox.pending()[0]
        self.assertEqual((notice["source_username"], notice["source_platform"], notice["notification_type"],
                          notice["arguments"]), ("Actual Recipient", 0, 4, ""))
        self.assertEqual(notice["event_id"], event_id)

    def test_acknowledgement_is_idempotent_bookkeeping_without_live_donor(self):
        event_id = self.gift()
        receipt = self.ack(event_id)
        self.assertTrue(self.outbox.acknowledge(receipt))
        self.assertTrue(self.outbox.acknowledge(receipt))
        self.assertEqual(self.outbox.pending(), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT accepted_at FROM notification_outbox").fetchone()[0], receipt["accepted_at"])

    def test_ack_rejects_other_account_old_session_and_mismatched_fields(self):
        event_id = self.gift()
        original = self.ack(event_id)
        for changes in ({"target_ps4_id": "sender"}, {"guid": "old-guid"}, {"source_username": "Fabricated"},
                        {"source_platform": 0}, {"notification_type": 1}, {"event_id": "f" * 32},
                        {"accepted_at": float("nan")}, {"accepted_at": time.time() + 3600},
                        {"source_platform": True}, {"format_version": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ProtocolError):
                    self.outbox.acknowledge(dict(original, **changes))
        self.store.bind_session("recipient", "newest-guid")
        with self.assertRaises(ProtocolError):
            self.outbox.acknowledge(original)
        self.assertEqual(len(self.outbox.pending()), 1)

    def test_export_and_ack_file_handoff_uses_exact_schema_and_is_idempotent(self):
        event_id = self.gift()
        path = self.outbox.export(self.path)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(snapshot), {"format_version", "generation", "entries"})
        self.assertEqual(snapshot["format_version"], 1)
        self.assertEqual(snapshot["entries"][0]["event_id"], event_id)
        directory = self.path / "notification-acks"
        directory.mkdir()
        receipt = self.ack(event_id)
        (directory / (event_id + ".json")).write_text(json.dumps(receipt), encoding="utf-8-sig")
        (directory / ("a" * 32 + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
        (directory / ("b" * 32 + ".json")).write_text("[]", encoding="utf-8")
        (directory / ("c" * 32 + ".json")).write_text("invalid", encoding="utf-8")
        self.assertEqual(self.outbox.import_acknowledgements(self.path), 1)
        self.assertEqual(self.outbox.import_acknowledgements(self.path), 1)
        self.assertEqual(self.outbox.pending(), [])
        self.outbox.export(self.path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["entries"], [])
        self.assertEqual(len(list(self.path.glob("*.tmp"))), 0)

    def test_invalid_names_payloads_targets_and_reused_keys_fail_closed(self):
        event_id = self.gift()
        for target, source, title, key in (("missing", "sender", "Item", "a"),
            ("recipient", "missing", "Item", "b"), ("recipient", "sender", "bad#field", "c"),
            ("recipient", "sender", "bad\nfield", "d"), ("recipient", "sender", "", "e"),
            ("recipient", "sender", "Different Item", "gift-one")):
            with self.subTest(key=key):
                with self.assertRaises(ProtocolError):
                    with self.store.atomic():
                        self.outbox.enqueue_gift(target, source, title, key)
        self.assertEqual(self.outbox.pending()[0]["event_id"], event_id)

    def test_session_rollover_keeps_separate_immutable_receipts_and_imports_current_only(self):
        event_id = self.gift()
        old_guid, new_guid = "a" * 32, "b" * 32
        self.store.bind_session("recipient", old_guid)
        old_receipt = dict(self.ack(event_id), guid=old_guid)
        directory = self.path / "notification-acks"
        directory.mkdir()
        old_path = directory / (event_id + "-" + old_guid + ".json")
        old_path.write_text(json.dumps(old_receipt), encoding="utf-8")
        # No backend import occurred before a newer login replaced the session.
        self.store.bind_session("recipient", new_guid)
        self.assertEqual(self.outbox.import_acknowledgements(self.path), 0)
        self.assertEqual(len(self.outbox.pending()), 1)
        new_receipt = dict(self.ack(event_id), guid=new_guid)
        new_path = directory / (event_id + "-" + new_guid + ".json")
        new_path.write_text(json.dumps(new_receipt), encoding="utf-8")
        mismatch_path = directory / ("c" * 32 + "-" + new_guid + ".json")
        mismatch_path.write_text(json.dumps(new_receipt), encoding="utf-8")
        self.assertEqual(self.outbox.import_acknowledgements(self.path), 1)
        self.assertEqual(self.outbox.pending(), [])
        self.assertEqual(json.loads(old_path.read_text())["guid"], old_guid)
        self.assertEqual(json.loads(new_path.read_text())["guid"], new_guid)


if __name__ == "__main__":
    unittest.main()

