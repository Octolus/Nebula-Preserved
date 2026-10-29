from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import nac1
import run_plan


NONCE = "a" * 64


class Nac1Tests(unittest.TestCase):
    def test_encode_and_movement_deadline_cap(self):
        payload = nac1.encode_command(NONCE, 4, "movement.forward", None, 100, 30_000)
        self.assertEqual(payload, ("NAC1\n" + NONCE + "\n4\n3100\nmovement.forward\n").encode("ascii"))

    def test_action_and_argument_validation(self):
        with self.assertRaises(ValueError):
            nac1.encode_command(NONCE, 1, "unknown", None, 1, 1)
        with self.assertRaises(ValueError):
            nac1.encode_command(NONCE, 1, "query", "extra", 1, 1)
        with self.assertRaises(ValueError):
            nac1.encode_command(NONCE, 1, "housing.command", "remove|bad id|item", 1, 1)
        self.assertIn(b"\ntravel|Home\n", nac1.encode_command(
            NONCE, 1, "housing.command", "travel|Home", 1, 1
        ))

    def test_result_identity_and_exact_assertions(self):
        raw = json.dumps({
            "nonce": NONCE, "sequence": 2, "action": "query", "status": "ok",
            "snapshot": {"network": {"ready": True}},
        }).encode()
        value = nac1.checked_result(raw, NONCE, 2, "query")
        nac1.require_values(value, {"snapshot.network.ready": True})
        with self.assertRaises(nac1.ProtocolError):
            nac1.checked_result(raw, NONCE, 3, "query")
        with self.assertRaises(nac1.ProtocolError):
            nac1.require_values(value, {"snapshot.network.ready": 1})

    def test_publish_refuses_any_occupied_slot(self):
        with tempfile.TemporaryDirectory() as root:
            session = nac1.Session(Path(root), NONCE, clock=lambda: 1.0)
            (Path(root) / "command.txt").write_text("existing", encoding="utf-8")
            with self.assertRaises(nac1.ProtocolError):
                session.publish(1, "query", None, 1000)

    def test_publish_uses_pending_then_command(self):
        with tempfile.TemporaryDirectory() as root:
            session = nac1.Session(Path(root), NONCE, clock=lambda: 1.0)
            session.publish(1, "query", None, 1000)
            self.assertFalse((Path(root) / "command.pending").exists())
            self.assertEqual(
                (Path(root) / "command.txt").read_bytes(),
                ("NAC1\n" + NONCE + "\n1\n2000\nquery\n").encode("ascii"),
            )


class PlanTests(unittest.TestCase):
    def _write_plan(self, root: Path, value):
        path = root / "plan.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_mutation_must_be_declared(self):
        with tempfile.TemporaryDirectory() as root:
            path = self._write_plan(Path(root), {
                "format_version": 1, "name": "bad", "mutating": False,
                "steps": [{"action": "movement.forward"}],
            })
            with self.assertRaises(nac1.ProtocolError):
                run_plan.load_plan(path)

    def test_nonmutating_plan_loads(self):
        with tempfile.TemporaryDirectory() as root:
            path = self._write_plan(Path(root), {
                "format_version": 1, "name": "query", "mutating": False,
                "steps": [{"action": "query", "expect_status": ["ok"]}],
            })
            self.assertEqual(run_plan.load_plan(path)["name"], "query")

    def test_all_repository_plans_validate(self):
        plans = sorted((HERE / "plans").glob("*.json"))
        self.assertEqual(len(plans), 6)
        loaded = [run_plan.load_plan(path) for path in plans]
        self.assertEqual(len({plan["name"] for plan in loaded}), 6)
        self.assertTrue(any(plan["mutating"] for plan in loaded))
        self.assertTrue(any(not plan["mutating"] for plan in loaded))

    def test_execute_action_and_poll(self):
        class FakeSession:
            def __init__(self):
                self.calls = []

            def submit(self, sequence, action, argument=None, timeout_ms=0):
                self.calls.append((sequence, action, argument, timeout_ms))
                pending = len(self.calls) < 3
                return {
                    "nonce": NONCE, "sequence": sequence, "action": action, "status": "ok",
                    "snapshot": {"movement": {"pending": pending}},
                }

        session = FakeSession()
        plan = {
            "steps": [
                {"action": "query", "expect_status": ["ok"]},
                {"poll": {"action": "query", "max_seconds": 1, "interval_ms": 10,
                          "until": {"snapshot.movement.pending": False}}},
            ]
        }
        records = run_plan.execute_plan(session, plan, 10)
        self.assertEqual([call[0] for call in session.calls], [10, 11, 12])
        self.assertEqual(records[-1]["result"]["snapshot"]["movement"]["pending"], False)


if __name__ == "__main__":
    unittest.main()
