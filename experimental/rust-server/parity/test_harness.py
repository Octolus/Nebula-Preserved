"""Negative controls for the comparator that is used to claim case matches."""
import copy
import json
import unittest
import tempfile

from common import scratch
from pathlib import Path
from run_parity import compare, normalized_state
from common import HERE
from fixture_support import validate_fixture, apply_fixture


class ComparatorControls(unittest.TestCase):
    def setUp(self):
        self.case = {"op": "http", "expected_status": 200}
        self.reply = {"ok": True, "status": 200, "body": "exact-ciphertext", "plaintext": "true#", "content_type": "text/plain"}
        self.whitelist = {"http": [], "durable_state": [{"table": "profiles", "column": "created_at"}]}

    def test_exact_http(self):
        self.assertEqual(compare(self.case, self.reply, copy.deepcopy(self.reply), self.whitelist)[0], "PASS")

    def test_each_http_observation_matters(self):
        for key, wrong in [("status", 400), ("body", "different"), ("plaintext", "true##"), ("content_type", "application/json")]:
            with self.subTest(key=key):
                changed = {**self.reply, key: wrong}
                self.assertEqual(compare(self.case, self.reply, changed, self.whitelist), ("FAIL", [key]))

    def test_json_scalar_types_matter(self):
        self.assertEqual(compare(self.case, self.reply, {**self.reply, "status": "200"}, self.whitelist)[0], "FAIL")

    def test_missing_plaintext_is_failure_not_null(self):
        changed = dict(self.reply)
        del changed["plaintext"]
        self.assertEqual(compare(self.case, self.reply, changed, self.whitelist)[0], "FAIL")

    def test_unimplemented_is_not_proven(self):
        self.assertEqual(compare(self.case, self.reply, {"ok": False, "error": "NOT_IMPLEMENTED"}, self.whitelist)[0], "NOT_PROVEN")

    def test_no_candidate_is_reference_only(self):
        self.assertEqual(compare(self.case, self.reply, None, self.whitelist)[0], "REFERENCE_ONLY")

    def test_reference_status_assertion_cannot_pass(self):
        self.assertEqual(compare({"op": "http", "expected_status": 403}, self.reply, self.reply, self.whitelist)[0], "REFERENCE_ERROR")

    def state(self, clock=1000.0, balance=1):
        return {"tables": {"profiles": {"columns": [{"name": "created_at", "type": "REAL"}, {"name": "balance", "type": "INTEGER"}],
                                           "rows": [{"created_at": clock, "balance": balance}]}}}

    def state_compare(self, left, right):
        return compare({"op": "snapshot"}, {"ok": True, "state": left}, {"ok": True, "state": right}, self.whitelist)[0]

    def test_only_approved_clock_normalized(self):
        self.assertEqual(self.state_compare(self.state(1000.0), self.state(2000.0)), "PASS")
        self.assertEqual(self.state_compare(self.state(balance=1), self.state(balance=2)), "FAIL")

    def test_durable_numeric_types_preserved(self):
        self.assertEqual(self.state_compare(self.state(balance=1), self.state(balance=1.0)), "FAIL")
        self.assertEqual(self.state_compare(self.state(1000), self.state(1000.0)), "FAIL")

    def test_zero_null_invalid_clock_not_hidden(self):
        self.assertEqual(self.state_compare(self.state(0.0), self.state(1000.0)), "FAIL")
        self.assertEqual(self.state_compare(self.state(None), self.state(1000.0)), "FAIL")
        for invalid in (-1.0, "1000", True):
            with self.subTest(clock=invalid):
                with self.assertRaises(ValueError):
                    normalized_state(self.state(invalid), self.whitelist)

    def test_extra_empty_table_not_hidden(self):
        changed = self.state()
        changed["tables"]["extra"] = {"columns": [], "rows": []}
        self.assertEqual(self.state_compare(self.state(), changed), "FAIL")

    def test_partial_row_is_invalid(self):
        changed = self.state()
        del changed["tables"]["profiles"]["rows"][0]["balance"]
        self.assertEqual(self.state_compare(self.state(), changed), "FAIL")

    def test_state_path_cannot_escape_owned_directory(self):
        for path in (HERE.parent / "synthetic-forbidden", HERE / ".." / "synthetic-forbidden", Path("../synthetic-forbidden")):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    scratch(path)

    def test_owned_scratch_is_portable_and_accepts_contained_paths(self):
        temp_root = scratch(HERE / "temp")
        with tempfile.TemporaryDirectory(prefix="controls-", dir=temp_root) as owned:
            target = Path(owned).resolve()
            self.assertTrue(target.is_relative_to(HERE))
            self.assertEqual(scratch(target / "nested"), target / "nested")
            relative = target.relative_to(HERE) / "relative"
            self.assertEqual(scratch(relative), target / "relative")

    def test_symlink_cannot_redirect_scratch_outside_owned_root(self):
        temp_root = scratch(HERE / "temp")
        with tempfile.TemporaryDirectory(prefix="link-controls-", dir=temp_root) as owned:
            target = Path(owned).resolve()
            self.assertTrue(target.is_relative_to(HERE))
            link = target / "outside-link"
            try:
                link.symlink_to(HERE.parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation unavailable")
            with self.assertRaises(ValueError):
                scratch(link / "synthetic-forbidden")


class FixtureGuardControls(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((HERE / "fixtures/configured-mutations-v1.json").read_text())

    def test_reviewed_fixture_shape(self):
        self.assertIs(validate_fixture(self.fixture), self.fixture)

    def test_secret_or_unknown_table_rejected(self):
        self.fixture["tables"]["public_access_credentials"] = []
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_unknown_column_rejected(self):
        self.fixture["tables"]["shop_wallets"][0]["password"] = "synthetic"
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_non_synthetic_account_rejected(self):
        self.fixture["accounts"][0]["account_id"] = "external-account"
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_mutated_reviewed_fixture_cannot_seed(self):
        self.fixture["tables"]["shop_wallets"][0]["crystals"] += 1
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_FIXTURE_CONTENT_MISMATCH"):
            apply_fixture(None, self.fixture)

    def test_nested_value_cannot_supply_code_or_sql(self):
        self.fixture["tables"]["shop_wallets"][0]["crystals"] = {"sql": "synthetic-rejected"}
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_default_clock_whitelist_unchanged(self):
        base = json.loads((HERE / "normalization.json").read_text())
        configured = json.loads((HERE / "fixtures/normalization.json").read_text())
        self.assertEqual(len(base["durable_state"]), 7)
        self.assertEqual(len(configured["durable_state"]), 14)
        self.assertEqual(base["http"], [])
        self.assertEqual(configured["http"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
