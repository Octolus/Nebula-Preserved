"""Pure offline tests for recovered consumable envelopes and local policy."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from consumables import Consumables, claim_receipt_file, read_receipt
from state import Store
from wire import ProtocolError


class ConsumableContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-consumable-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("No network in consumable tests"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "preservation.sqlite3")
        self.store.account("account-a")
        self.store.account("account-b")
        self.store.bind_session("account-a", "guid-a")
        self.store.bind_session("account-b", "guid-b")
        self.source = Consumables(self.store, receipt_ttl=30)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def test_price_is_exact_nine_field_display_contract(self):
        self.assertEqual(self.source.price_response("account-a", "guid-a", "coffee", 0),
                         "true#guid-a#account-a#coffee##1#local token#0#false")
        self.source.grant("account-a", "coffee", 3, 7, "2", "local beans", 4, True)
        response = self.source.price_response("account-a", "guid-a", "coffee", 0)
        self.assertEqual(response, "true#guid-a#account-a#coffee##2#local beans#3#true")
        self.assertEqual(len(response.split("#")), 9)

    def test_issue_uses_opaque_uuid_not_balance_and_publishes_handoff(self):
        self.source.grant("account-a", "oktoberfest", 2, 11, reward_index=6)
        response = self.source.issue_response("account-a", "guid-a", "oktoberfest", 0, now=100.0)
        fields = response.split("#")
        self.assertEqual(fields[:6], ["true", "guid-a", "account-a", "oktoberfest", "", "true"])
        self.assertEqual(len(fields[6]), 32)
        self.assertEqual(fields[7], "6")
        self.assertNotEqual(fields[6], "1")
        receipt = read_receipt(self.path / "consumable-receipts" / (fields[6] + ".json"))
        self.assertEqual(receipt["use_count"], 11)
        self.assertEqual(receipt["expires_at"], 130.0)
        self.assertEqual(self.source.balance("account-a", "oktoberfest")["units"], 1)

    def test_empty_balance_returns_false_without_receipt_or_deduction(self):
        expected = "true#guid-a#account-a#coffee##false##0"
        self.assertEqual(self.source.issue_response("account-a", "guid-a", "coffee", 0), expected)
        self.source.grant("account-a", "coffee", 1, 4)
        self.source.issue_response("account-a", "guid-a", "coffee", 0)
        self.assertEqual(self.source.issue_response("account-a", "guid-a", "coffee", 0), expected)
        self.assertEqual(len(list((self.path / "consumable-receipts").glob("*.json"))), 1)

    def test_atomic_claim_is_one_use_and_import_is_idempotent(self):
        self.source.grant("account-a", "coffee", 1, 9)
        receipt_id = self.source.issue_response("account-a", "guid-a", "coffee", 0, now=200.0).split("#")[6]
        self.assertEqual(claim_receipt_file(self.path, receipt_id, "guid-a", "account-a", "coffee", now=201.0), 9)
        with self.assertRaises(ProtocolError):
            claim_receipt_file(self.path, receipt_id, "guid-a", "account-a", "coffee", now=201.0)
        self.assertEqual(self.source.import_claims(), {"applied": 1, "seen": 0, "invalid": 0})
        self.assertEqual(self.source.import_claims(), {"applied": 0, "seen": 1, "invalid": 0})
        row = self.store.db.execute("SELECT status FROM consumable_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        self.assertEqual(row[0], "claimed")

    def test_identity_kind_expiry_and_minigame_rejected_without_consuming(self):
        self.source.grant("account-a", "coffee", 1, 5)
        receipt_id = self.source.issue_response("account-a", "guid-a", "coffee", 0, now=300.0).split("#")[6]
        for args in (("guid-b", "account-a", "coffee", 301.0),
                     ("guid-a", "account-b", "coffee", 301.0),
                     ("guid-a", "account-a", "oktoberfest", 301.0),
                     ("guid-a", "account-a", "coffee", 331.0)):
            with self.assertRaises(ProtocolError):
                claim_receipt_file(self.path, receipt_id, *args[:3], now=args[3])
        self.assertTrue((self.path / "consumable-receipts" / (receipt_id + ".json")).exists())
        with self.assertRaises(ProtocolError):
            self.source.price_response("account-a", "guid-a", "picnic", 0)
        with self.assertRaises(ProtocolError):
            self.source.price_response("account-a", "guid-a", "coffee", 3)
        with self.assertRaises(ProtocolError):
            self.source.price_response("account-a", "guid-b", "coffee", 0)

    def test_grants_persist_and_use_policy_is_explicit(self):
        self.source.grant("account-a", "coffee", 2, 3)
        self.source.grant("account-a", "coffee", 4, 12, "free", "preservation", 8)
        self.store.close()
        self.store = Store(self.path / "preservation.sqlite3")
        self.source = Consumables(self.store)
        value = self.source.balance("account-a", "coffee")
        self.assertEqual((value["units"], value["prop_use_count"], value["reward_index"]), (6, 12, 8))
        self.assertEqual(self.source.list("account-b"), [])

    def test_tampered_claim_is_not_accepted(self):
        self.source.grant("account-a", "coffee", 1, 5)
        receipt_id = self.source.issue_response("account-a", "guid-a", "coffee", 0).split("#")[6]
        source = self.path / "consumable-receipts" / (receipt_id + ".json")
        value = json.loads(source.read_text(encoding="utf-8"))
        value["use_count"] = 999
        source.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(claim_receipt_file(self.path, receipt_id, "guid-a", "account-a", "coffee"), 999)
        self.assertEqual(self.source.import_claims(), {"applied": 0, "seen": 0, "invalid": 1})


if __name__ == "__main__":
    unittest.main()

