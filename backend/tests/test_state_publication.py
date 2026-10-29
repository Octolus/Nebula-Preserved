"""Offline regression for Windows snapshot replace sharing races."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from state import Store


class SnapshotPublication(unittest.TestCase):
    def test_transient_windows_share_denial_retries_unique_temp_without_losing_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "preservation.sqlite3"
            store = Store(database)
            try:
                store.account("durable-account", "Durable Player")
                store.bind_session("durable-account", "a" * 32)
                target = root / "instance-accounts.json"
                target.write_text('{"old":true}', encoding="utf-8")
                real_replace = os.replace
                denied_sources = []

                def sharing_race(source, destination):
                    if Path(destination) == target and len(denied_sources) < 3:
                        denied_sources.append(Path(source))
                        self.assertTrue(Path(source).is_file())
                        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
                        error = PermissionError("simulated active Mirror reader")
                        error.winerror = 5
                        raise error
                    return real_replace(source, destination)

                with patch("state.os.replace", side_effect=sharing_race), patch("state.time.sleep") as sleep:
                    store.export_instance_accounts(root)
                self.assertEqual(sleep.call_args_list, [call(0.01), call(0.02), call(0.04)])
                self.assertEqual(len({str(x) for x in denied_sources}), 1)
                self.assertNotEqual(denied_sources[0], target.with_suffix(".json.tmp"))
                snapshot = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual([x["ps4_id"] for x in snapshot["accounts"]], ["durable-account"])
                self.assertEqual(list(root.glob(".instance-accounts.json.*.tmp")), [])
            finally:
                store.close()

            reopened = Store(database)
            try:
                self.assertEqual(reopened.account("durable-account")["username"], "Durable Player")
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()

