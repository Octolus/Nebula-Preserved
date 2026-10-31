"""Every account owns Home plus a configurable starter set; staff can grant/remove."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent / "tools")]
from apartments import DEFAULT_STARTER_APARTMENTS, starter_apartments
from housing import HousingStore
from management import Management, ManagementError
from service import Service
from space_shop import SHOP_ID_BY_SPACE, SHOP_SPACES
from state import Catalog, Store
from wire import session_guid

TOKEN = b"synthetic-apartment-service-token-0000001"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]
DEFAULT = ("CliffApartment", "Home", "LakeApartment")


class StarterApartmentTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket, "socket", side_effect=AssertionError("sockets forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NEBULA_STARTER_APARTMENTS", None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stores = []
        self.counter = 0

    def open(self, managed=True, starter=None):
        if starter is None:
            os.environ.pop("NEBULA_STARTER_APARTMENTS", None)
        else:
            os.environ["NEBULA_STARTER_APARTMENTS"] = starter
        for store in self.stores:
            store.close()
        store = Store(self.root / "preservation.sqlite3")
        self.stores = [store]
        self.addCleanup(store.close)
        self.store = store
        self.service = Service(store, Catalog(BACKEND.parent / "protocol"),
                               core_test_profile="nonmini-semantic-v1" if managed else None,
                               managed_instances=managed)
        self.manager = Management(store, self.service, TOKEN, OPERATORS)
        return self.service

    def login(self, account_id):
        self.service.dispatch("N2UserExist", "#".join(
            (account_id, "v72", "false", account_id, "nonce", "StandaloneWindows")))
        request_hash = (account_id.encode().hex() + "0" * 64)[:64]
        self.service.dispatch("ChannelGUIDServlet", "#".join((account_id, request_hash, "StandaloneWindows")))
        return session_guid(account_id, request_hash)

    def owned(self, account_id):
        return tuple(self.service.housing.personal_spaces(account_id))

    def ids(self, account_id):
        return dict(self.store.db.execute(
            "SELECT logical_space_key,instance_id FROM housing_spaces WHERE owner_ps4_id=?", (account_id,)).fetchall())

    def command(self, account_id, action, body, role="admin", key=None):
        self.counter += 1
        headers = {"Authorization": "Bearer " + TOKEN.decode(), "X-Management-Actor": role,
                   "Idempotency-Key": key or f"apartment-{self.counter:08}"}
        return self.manager.command("users/" + account_id + "/character/housing/" + action, body, headers)

    def read(self, account_id, tail):
        actor = self.manager.actor({"Authorization": "Bearer " + TOKEN.decode(),
                                    "X-Management-Actor": "moderator"}, "read")
        return self.manager.read("users/" + account_id + "/character/" + tail, {}, actor)

    # ---- policy configuration ----------------------------------------------
    def test_configuration_always_includes_home_and_rejects_unknown_names(self):
        self.assertEqual(starter_apartments({}), DEFAULT_STARTER_APARTMENTS)
        self.assertEqual(starter_apartments({"NEBULA_STARTER_APARTMENTS": " "}), DEFAULT_STARTER_APARTMENTS)
        self.assertEqual(starter_apartments({"NEBULA_STARTER_APARTMENTS": "Home"}), ("Home",))
        self.assertEqual(starter_apartments({"NEBULA_STARTER_APARTMENTS": "TheCrypt, Home,TheCrypt"}),
                         ("Home", "TheCrypt"))
        for bad in ("home", "Cube", "Nexus", "SorcerersEyrie1", "Home;Greenhouse"):
            with self.assertRaises(ValueError):
                starter_apartments({"NEBULA_STARTER_APARTMENTS": bad})
        with self.assertRaises(ValueError):
            self.open(starter="NotAnApartment")

    # ---- new and existing accounts -----------------------------------------
    def test_new_account_owns_default_set_and_navigator_lists_it(self):
        self.open()
        guid = self.login("new-player")
        self.assertEqual(self.owned("new-player"), DEFAULT)
        response = self.service.dispatch("GetPersonalSpacesServlet", "#".join((guid, "new-player", "StandaloneWindows")))
        self.assertEqual(response, "#".join(("true", guid, "new-player", "!".join(DEFAULT))))
        fields = self.service.housing.purchase_fields("new-player")
        # Asset = shop ID (Home has none), name = navigator name.
        self.assertEqual(tuple(fields["personalspacesName"]), DEFAULT)
        self.assertEqual(tuple(fields["personalspaces"]), (SHOP_ID_BY_SPACE["CliffApartment"], "Home",
                                                          SHOP_ID_BY_SPACE["LakeApartment"]))
        managed = {row["logical_space_key"]: row for row in self.store.db.execute(
            "SELECT * FROM managed_instances WHERE owner_ps4_id='new-player'")}
        self.assertEqual(set(managed), set(DEFAULT))
        self.assertTrue(all(row["kind"] == "personal" and row["instance_id"].startswith("apt-") for row in managed.values()))
        grants = {r["logical_space_key"]: r for r in self.store.db.execute(
            "SELECT * FROM starter_apartment_grants WHERE ps4_id='new-player'")}
        self.assertEqual(set(grants), set(DEFAULT))
        self.assertTrue(all(g["created_binding"] == 1 and g["policy_source"] == "starter_apartments_v1" for g in grants.values()))
        # Repeated logins are idempotent.
        before = self.ids("new-player")
        self.login("new-player")
        self.assertEqual(self.ids("new-player"), before)
        # Home can be loaded through the normal managed flow.
        self.assertEqual(self.service.dispatch("N2LoadSpace", "#".join(
            (guid, "new-player", "CliffApartment", "false", "", "", "StandaloneWindows"))), guid + "#false#false")

    def test_startup_backfills_existing_accounts_once_and_exports_bindings(self):
        store = Store(self.root / "preservation.sqlite3")
        store.account("veteran", "Veteran")
        store.account("tester", "Tester")
        HousingStore(store, BACKEND.parent / "protocol").bind_space("legacy-home", "Home", "veteran")
        # The earlier policy grandfathered preexisting accounts with nothing.
        store.db.execute("CREATE TABLE managed_account_policy (ps4_id TEXT PRIMARY KEY REFERENCES profiles,"
                         " default_home INTEGER NOT NULL CHECK(default_home IN (0,1)),"
                         " policy_source TEXT NOT NULL, created_at REAL NOT NULL)")
        store.db.execute("INSERT INTO managed_account_policy VALUES('tester',0,'preexisting_before_managed_mode',0)")
        store.db.commit()
        store.close()
        self.open()
        for account in ("veteran", "tester"):
            self.assertEqual(self.owned(account), DEFAULT)
        self.assertEqual(self.ids("veteran")["Home"], "legacy-home")
        legacy = self.store.db.execute("SELECT * FROM starter_apartment_grants WHERE ps4_id='veteran' AND logical_space_key='Home'").fetchone()
        self.assertEqual((legacy["instance_id"], legacy["created_binding"]), ("legacy-home", 0))
        adopted = self.store.db.execute("SELECT adopted_existing FROM managed_instances WHERE instance_id='legacy-home'").fetchone()
        self.assertEqual(adopted[0], 1)
        snapshot = json.loads(self.service.housing.export_bindings(self.root).read_text(encoding="utf-8"))
        exported = {(b["owner_ps4_id"], b["logical_space_key"]): b["instance_id"] for b in snapshot["bindings"]}
        self.assertEqual(len(exported), 6)
        self.assertEqual(exported[("veteran", "Home")], "legacy-home")
        ids = {account: self.ids(account) for account in ("veteran", "tester")}
        grants = self.store.db.execute("SELECT COUNT(*) FROM starter_apartment_grants").fetchone()[0]
        self.open()  # second startup: nothing new
        self.assertEqual({account: self.ids(account) for account in ids}, ids)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM starter_apartment_grants").fetchone()[0], grants)

    def test_backfill_never_removes_and_never_regrants_a_removed_starter(self):
        self.open()
        self.login("player")
        self.command("player", "remove", {"space_key": "CliffApartment"})
        self.open(starter="Home")  # shrunk configuration
        self.assertEqual(self.owned("player"), ("Home", "LakeApartment"))
        self.open()  # default again: the removed starter stays removed
        self.assertEqual(self.owned("player"), ("Home", "LakeApartment"))
        self.open(starter="Home,Greenhouse")  # grown configuration: applied once
        self.assertEqual(self.owned("player"), ("Greenhouse", "Home", "LakeApartment"))
        self.login("player")
        self.assertEqual(self.owned("player"), ("Greenhouse", "Home", "LakeApartment"))

    def test_configured_set_applies_to_new_accounts(self):
        self.open(starter="TheCrypt,WindMillFarmHouse")
        self.login("custom")
        self.assertEqual(self.owned("custom"), ("Home", "TheCrypt", "WindMillFarmHouse"))
        self.open(starter="Home")
        self.login("minimal")
        self.assertEqual(self.owned("minimal"), ("Home",))

    def test_manual_mode_provisions_nothing_but_staff_can_grant(self):
        self.open(managed=False)
        self.login("manual")
        self.assertEqual(self.owned("manual"), ())
        self.assertEqual(self.service.apartments.spaces, ())
        result = self.command("manual", "grant", {"space_key": "Home"})
        self.assertTrue(result["changed"])
        self.assertEqual(self.owned("manual"), ("Home",))

    # ---- staff management -----------------------------------------------------
    def test_staff_grant_and_remove_are_audited_idempotent_and_reuse_identity(self):
        self.open()
        self.login("player")
        options = self.read("player", "housing-options")
        self.assertEqual(options["total"], 31)
        self.assertEqual(options["items"][0]["space_key"], "Home")
        self.assertEqual({o["space_key"] for o in options["items"] if o["owned"]}, set(DEFAULT))
        with self.assertRaises(ManagementError) as denied:
            self.command("player", "grant", {"space_key": "Greenhouse"}, role="moderator")
        self.assertEqual(denied.exception.status, 403)
        granted = self.command("player", "grant", {"space_key": "Greenhouse"}, key="grant-greenhouse")
        self.assertTrue(granted["changed"])
        self.assertEqual(granted["after"]["space_key"], "Greenhouse")
        self.assertTrue(self.command("player", "grant", {"space_key": "Greenhouse"}, key="grant-greenhouse")["replayed"])
        self.assertFalse(self.command("player", "grant", {"space_key": "Greenhouse"})["changed"])
        instance = self.ids("player")["Greenhouse"]
        self.assertIsNotNone(self.store.db.execute("SELECT 1 FROM managed_instances WHERE instance_id=?", (instance,)).fetchone())
        audit = self.store.db.execute("SELECT operation,reason FROM management_audit WHERE request_id=?",
                                      (granted["request_id"],)).fetchone()
        self.assertEqual(tuple(audit), ("players.data", "No reason given"))
        for bad in ({"space_key": "Nexus"}, {"space_key": "greenhouse"}, {}, {"space_key": "Home", "extra": 1}):
            with self.assertRaises(ManagementError):
                self.command("player", "grant", bad)

        layout = self.service.housing.empty_layout("Greenhouse")
        with self.store.db:
            self.store.db.execute("INSERT INTO housing_layouts VALUES(?,?,?)", (instance, json.dumps(layout), time.time()))
        removed = self.command("player", "remove", {"space_key": "Greenhouse"})
        self.assertTrue(removed["changed"])
        self.assertEqual(removed["before"]["layout"], layout)
        self.assertNotIn("Greenhouse", self.owned("player"))
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM housing_layouts WHERE instance_id=?", (instance,)).fetchone())
        with self.assertRaises(ManagementError) as missing:
            self.command("player", "remove", {"space_key": "Greenhouse"})
        self.assertEqual(missing.exception.status, 404)
        # Re-granting reuses the stable managed identity (UNIQUE owner/space).
        self.command("player", "grant", {"space_key": "Greenhouse"})
        self.assertEqual(self.ids("player")["Greenhouse"], instance)
        with self.assertRaises(ManagementError) as home:
            self.command("player", "remove", {"space_key": "Home"})
        self.assertEqual(home.exception.status, 409)
        view = {row["space_key"]: row for row in self.read("player", "housing")["items"]}
        self.assertEqual((view["Home"]["default"], view["Home"]["removable"]), (True, False))
        self.assertEqual((view["LakeApartment"]["starter"], view["Greenhouse"]["starter"]), (True, False))

    def test_remove_is_refused_while_the_apartment_is_in_use(self):
        self.open()
        guid = self.login("player")
        instance = self.ids("player")["LakeApartment"]
        with self.store.db:
            self.store.db.execute("INSERT INTO allocations VALUES(?,?,?,?,?,?)",
                                  (guid, instance, "LakeApartment", "127.0.0.1", 28001, time.time()))
        path = self.root / "instances" / instance / "instance-presence.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format_version": 1, "generation": time.time(), "instance_id": instance,
                                    "psidglobal": "LakeApartment", "players": [{"guid": guid, "status": 0}]}),
                        encoding="utf-8")
        with self.assertRaises(ManagementError) as busy:
            self.command("player", "remove", {"space_key": "LakeApartment"})
        self.assertEqual(busy.exception.status, 409)
        self.assertIn("LakeApartment", self.owned("player"))
        path.unlink()
        self.assertTrue(self.command("player", "remove", {"space_key": "LakeApartment"})["changed"])
        # A hand-made binding with a new ID conflicts with the retained managed
        # identity; login and startup must still succeed and leave it alone.
        self.service.housing.bind_space("manual-lake", "LakeApartment", "player")
        self.login("player")
        self.open()
        self.assertEqual(self.ids("player")["LakeApartment"], "manual-lake")


if __name__ == "__main__":
    unittest.main()
