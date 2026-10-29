"""Native enum request names joined to the distinct preference JSON fields."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from service import Service
from state import Catalog, Store
from wire import ProtocolError


class NativeSettings(unittest.TestCase):
    def fixture(self, path):
        store = Store(path)
        guid = "d" * 32
        store.account("offline-settings", "Settings Fixture")
        store.bind_session("offline-settings", guid)
        return store, guid, Service(store, Catalog(BACKEND.parent / "protocol"))

    def test_get_prefs_preserves_legacy_prefix_and_authors_platform_default(self):
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-settings-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with patch.object(socket, "socket", side_effect=AssertionError("No sockets in settings checks")):
            with tempfile.TemporaryDirectory(dir=scratch) as directory:
                store, guid, service = self.fixture(Path(directory) / "preservation.sqlite3")
                try:
                    response = service.dispatch(
                        "GetPlayerPrefsServlet", guid + "#offline-settings#StandaloneWindows")
                    fields = response.split("#")
                    self.assertEqual(fields[:2], ["true", guid])
                    self.assertEqual(fields[3:], ["prefs-v1", "0"])
                    legacy = response.split("#", 3)[:3]
                    self.assertEqual(legacy[:2], ["true", guid])
                    prefs = json.loads(legacy[2])
                    self.assertNotIn("PlatformOnly", prefs)
                    self.assertNotIn("ShowPets", prefs)
                finally:
                    store.close()

    def test_enum_notification_name_persists_as_native_json_field_across_reopen(self):
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-settings-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with patch.object(socket, "socket", side_effect=AssertionError("No sockets in settings checks")):
            with tempfile.TemporaryDirectory(dir=scratch) as directory:
                path = Path(directory) / "preservation.sqlite3"
                store = Store(path)
                guid = "d" * 32
                try:
                    store.account("offline-settings", "Settings Fixture")
                    store.bind_session("offline-settings", guid)
                    service = Service(store, Catalog(BACKEND.parent / "protocol"))
                    response = service.dispatch("SavePlayerPref", guid + "#NotificationLoginFriend#0#StandaloneWindows")
                    self.assertEqual(response, "true#" + guid)
                    prefs = json.loads(service.dispatch("GetPlayerPrefsServlet", guid + "#offline-settings#StandaloneWindows").split("#")[2])
                    self.assertEqual(prefs["notificationLoginFriend"], 0)
                    self.assertNotIn("NotificationLoginFriend", prefs)
                    with self.assertRaises(ProtocolError):
                        service.dispatch("SavePlayerPref", guid + "#NOTIFICATIONLOGINVALID#1#StandaloneWindows")
                finally:
                    store.close()
                reopened = Store(path)
                try:
                    service = Service(reopened, Catalog(BACKEND.parent / "protocol"))
                    self.assertEqual(reopened.preferences("offline-settings")["notificationLoginFriend"], 0)
                    # The legacy four-field wrapper reaches the same save path.
                    response = service.dispatch("SetPlayerPrefsServlet", guid + "#offline-settings#NotificationLoginFriend#1#StandaloneWindows")
                    self.assertEqual(response, "true#" + guid)
                    self.assertEqual(reopened.preferences("offline-settings")["notificationLoginFriend"], 1)
                    self.assertIsNone(reopened.db.execute("SELECT key FROM preferences WHERE key='NotificationLoginFriend'").fetchone())
                finally:
                    reopened.close()

    def test_platform_only_persists_and_hydrates_only_in_versioned_trailer(self):
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-settings-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with patch.object(socket, "socket", side_effect=AssertionError("No sockets in settings checks")):
            with tempfile.TemporaryDirectory(dir=scratch) as directory:
                path = Path(directory) / "preservation.sqlite3"
                store, guid, service = self.fixture(path)
                try:
                    self.assertEqual(service.dispatch(
                        "SavePlayerPref", guid + "#PlatformOnly#1#StandaloneWindows"),
                        "true#" + guid)
                    fields = service.dispatch(
                        "GetPlayerPrefsServlet", guid + "#offline-settings#StandaloneWindows").split("#")
                    self.assertEqual(fields[3:], ["prefs-v1", "1"])
                    self.assertNotIn("PlatformOnly", json.loads(fields[2]))
                finally:
                    store.close()

                reopened = Store(path)
                try:
                    service = Service(reopened, Catalog(BACKEND.parent / "protocol"))
                    fields = service.dispatch(
                        "GetPlayerPrefsServlet", guid + "#offline-settings#StandaloneWindows").split("#")
                    self.assertEqual(fields[3:], ["prefs-v1", "1"])
                    self.assertEqual(reopened.preferences("offline-settings")["PlatformOnly"], 1)
                    self.assertNotIn("ShowPets", json.loads(fields[2]))
                finally:
                    reopened.close()


if __name__ == "__main__":
    unittest.main()

