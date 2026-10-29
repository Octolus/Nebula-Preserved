"""Mutation controls ensure normalization cannot conceal protocol/state defects."""
from datetime import datetime, timezone
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.normalize import Normalizer, clock
from run_parity import canonical


class Controls(unittest.TestCase):
    def normalizer(self):
        return Normalizer({"durable_state": []})

    def test_uncorrelated_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNCORRELATED"):
            self.normalizer().request_id("a" * 32)

    def test_uuid_reuse_for_other_operation_rejected(self):
        n = self.normalizer(); n.bind("a" * 32, "operation-a")
        with self.assertRaisesRegex(ValueError, "REUSED"):
            n.bind("a" * 32, "operation-b")

    def test_fresh_uuid_on_replay_remains_mismatch(self):
        n = self.normalizer()
        for case, identity in (("credit", "a" * 32), ("replay", "b" * 32)):
            n.observe({"op": "admin", "id": case}, {"ok": True, "status": 200, "body": {"data": {"request_id": identity}}})
        self.assertNotEqual(n.result({"request_id": "a" * 32}), n.result({"request_id": "b" * 32}))

    def test_news_uuid_must_derive_from_known_request(self):
        n = self.normalizer(); n.bind("a" * 32, "publish")
        with self.assertRaisesRegex(ValueError, "UNCORRELATED"):
            n.news_id("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    def test_date_label_cannot_be_arbitrary(self):
        n = self.normalizer(); n.bind("a" * 32, "publish")
        with self.assertRaisesRegex(ValueError, "NEWS_DATE"):
            n.payload({"news_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "created_at": 1700000000, "date_label": "wrong"})

    def test_maintenance_relative_deadline_preserved(self):
        n = self.normalizer()
        self.assertNotEqual(n.payload({"started_at": 1700000000, "end_at": 1700000300}),
                            n.payload({"started_at": 1700000001, "end_at": 1700000361}))
        with self.assertRaisesRegex(ValueError, "DEADLINE"):
            n.payload({"started_at": 1700000000, "end_at": 1700000301})

    def test_storage_type_zero_null_preserved(self):
        self.assertNotEqual(clock(1700000000), clock(1700000000.0))
        self.assertEqual(clock(0), 0); self.assertIsNone(clock(None))
        for invalid in (True, -1, "1700000000", float("inf")):
            with self.assertRaises(ValueError):
                clock(invalid)

    def test_nonclock_fields_and_list_order_remain_exact(self):
        n = self.normalizer()
        for first, second in (({"crystals": 1}, {"crystals": 2}), ({"expires_at": 1}, {"expires_at": 2}),
                              ({"label": "a"}, {"label": "b"}), ({"items": [1, 2]}, {"items": [2, 1]})):
            self.assertNotEqual(n.payload(first), n.payload(second))

    def test_command_scalar_types_remain_exact(self):
        n = self.normalizer()
        self.assertNotEqual(canonical(n.result({"changed": True})), canonical(n.result({"changed": 1})))

    def test_unknown_table_clock_cannot_be_normalized(self):
        n = self.normalizer()
        def state(value):
            return {"tables": {"future_table": {"columns": [{"name": "created_at", "type": "REAL"}], "rows": [{"created_at": value}]}}}
        self.assertNotEqual(n.state(state(1700000000.0)), n.state(state(1700000001.0)))

    def test_noncanonical_audit_text_rejected(self):
        n = self.normalizer(); n.bind("a" * 32, "test")
        fields = {"request_id": "a" * 32, "operation": "test", "target_id": "target", "created_at": 1.0,
                  "before_json": '{"x": 1}', "after_json": 'null'}
        state = {"tables": {"management_audit": {"columns": [{"name": name, "type": "TEXT"} for name in fields], "rows": [fields]}}}
        with self.assertRaisesRegex(ValueError, "NONCANONICAL"):
            n.state(state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
