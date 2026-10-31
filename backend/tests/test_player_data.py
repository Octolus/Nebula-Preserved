"""Disposable database tests of operator character views and audited edits."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools")]
from management import Management, ManagementError
from resource_selection import SelectionAuthority
from service import Service
from state import Catalog, Store
from wire import json_field


TOKEN = b"synthetic-player-data-service-token-000001"
ACCOUNT = "player-data-fixture-player"
FRIEND = "player-data-fixture-friend"
OPERATORS = [{"id": role, "role": role, "enabled": True} for role in ("owner", "admin", "moderator")]


class PlayerDataContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.addCleanup(self.store.close)
        self.service = Service(self.store, self.catalog)
        self.selection = SelectionAuthority(self.store, self.service.resources)
        self.manager = Management(self.store, self.service, TOKEN, OPERATORS)
        self.service.ensure_default_avatars(self.store.account(ACCOUNT, "Fixture Player"))
        self.store.account(FRIEND, "Fixture Friend")
        self.db = self.store.db
        self.counter = 0
        defaults = json.loads((ROOT / "protocol" / "avatar-default-catalog.json").read_text(encoding="utf-8"))
        self.starter = {row["item_id"] for row in defaults["defaults"]["MALE"]["items"]}
        controls = {r["item_id"] for r in self.service.wardrobe_removal_sentinels.values()}
        self.extra = next(x for x in self.service.catalog.items.values()
                          if x["gender"] == "MALE" and x["item_id"] not in self.starter | controls
                          and sum(i == x["item_id"] for i, g, _c in self.service.catalog.items if g == "MALE") == 1)

    def headers(self, role="admin", key=None):
        self.counter += 1
        return {"Authorization": "Bearer " + TOKEN.decode(), "X-Management-Actor": role,
                "Idempotency-Key": key or f"player-data-{self.counter:08}"}

    def read(self, tail="", query=None, role="moderator"):
        actor = self.manager.actor(self.headers(role), "read")
        return self.manager.read("users/" + ACCOUNT + "/character" + tail, query or {}, actor)

    def command(self, tail, body, role="admin", key=None):
        return self.manager.command("users/" + ACCOUNT + "/character/" + tail,
                                    {"reason": "Synthetic character support", **body}, self.headers(role, key))

    def error(self, status, function, *args, **kwargs):
        with self.assertRaises(ManagementError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def wear_extra(self, name="Default"):
        """Native-equivalent saved outfit containing one granted extra item."""
        self.store.grant(ACCOUNT, self.extra)
        row = self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND name=? AND gender='MALE'", (ACCOUNT, name)).fetchone()
        preset, assets = json.loads(row["preset_json"]), json.loads(row["assets_json"])
        preset["item6"] = self.extra["item_id"]
        parts = assets["data"].split("!")
        half = len(parts) // 2
        assets["data"] = "!".join(parts[:half] + [self.extra["item_id"]] + parts[half:] + [self.extra["category"]])
        with self.db:
            self.db.execute("UPDATE presets SET preset_json=?,assets_json=? WHERE ps4_id=? AND name=? AND gender='MALE'",
                            (json_field(preset), json_field(assets), ACCOUNT, name))

    def second_preset(self, name="Party"):
        row = dict(self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND gender='MALE'", (ACCOUNT,)).fetchone())
        self.store.save_preset(ACCOUNT, name, "MALE", json.loads(row["preset_json"]), json.loads(row["assets_json"]),
                               json.loads(row["position_json"]))

    def home(self):
        housing = self.service.housing
        binding = housing.ensure_binding(ACCOUNT, "Home")
        item = next(k for k, v in housing.catalog.items() if v["behaviour"] in ("ground", "floor"))
        other = next(k for k, v in housing.catalog.items() if v["behaviour"] in ("ground", "floor") and k != item)
        for value in (item, other):
            housing.grant_item(ACCOUNT, value)
        layout = housing.empty_layout(binding["psidglobal"])
        layout.update(aidasset=[item, other, item], aidasset_tx=[1.0, 2.0, 3.0], aidasset_ty=[0.0] * 3,
                      aidasset_tz=[4.0, 5.0, 6.0], aidasset_r=[90.0, 0.0, 180.0])
        with self.db:
            self.db.execute("INSERT INTO housing_layouts VALUES(?,?,?)", (binding["instance_id"], json_field(layout), time.time()))
        return binding, item, other

    def test_overview_shows_current_outfit_named_from_catalog_and_sections(self):
        overview = self.read()
        self.assertEqual((overview["username"], overview["gender"]), ("Fixture Player", "MALE"))
        outfit = overview["outfit"]
        self.assertEqual(outfit["preset_name"], "Default")
        self.assertEqual({i["item_id"] for i in outfit["items"]}, self.starter)
        for item in outfit["items"]:
            self.assertTrue(item["catalog_known"] and item["owned"] and item["starter"])
            self.assertTrue(item["preview_url"].startswith("/api/catalog-preview/"))
            self.assertTrue(item["label"] and item["category"])
            self.assertNotIn("asset_metadata", item)
        self.assertEqual([s["id"] for s in overview["sections"]],
                         ["presets", "items", "preferences", "social", "housing", "resources", "position", "consumables"])
        presets = next(s for s in overview["sections"] if s["id"] == "presets")
        self.assertEqual((presets["count"], presets["editable"]), (2, True))
        self.assertEqual(overview["genders"]["FEMALE"]["selected_preset"], "Default")
        self.assertTrue(overview["equipped"]["selection_supported"])
        self.assertIsNone(overview["equipped"]["companion"])
        self.assertEqual(overview["position"]["source"], "default")
        self.error(404, self.read, "/unknown")
        self.error(404, self.manager.read, "users/missing/character", {}, self.manager.actor(self.headers("moderator"), "read"))

    def test_presets_items_preferences_and_resources_sections(self):
        self.wear_extra()
        self.second_preset()
        page = self.read("/presets", {"gender": "MALE"})
        self.assertEqual([p["preset_name"] for p in page["items"]], ["Default", "Party"])
        self.assertEqual(page["selected"]["MALE"], "Party")
        detail = self.read("/presets/Default/MALE", {"raw": "1"})
        slot = next(i for i in detail["items"] if i["item_id"] == self.extra["item_id"])
        self.assertEqual((slot["slot"], slot["category"], slot["starter"]), (6, self.extra["category"], False))
        self.assertIn("raw", detail)
        self.error(404, self.read, "/presets/Missing/MALE")
        self.error(400, self.read, "/presets/Default/OTHER")
        items = self.read("/items", {"kind": "wardrobe", "q": self.extra["item_id"]})
        self.assertEqual(items["total"], 1)
        self.assertEqual(items["items"][0]["equipped_in"], ["Default", "Party"])
        self.assertTrue(items["items"][0]["revocable"])
        self.error(400, self.read, "/items", {"kind": "weapons"})
        self.store.save_preference(ACCOUNT, "Music", 0.25)
        prefs = {p["key"]: p for p in self.read("/preferences", {"limit": "100"})["items"]}
        self.assertEqual((prefs["Music"]["value"], prefs["Music"]["stored"], prefs["Music"]["label"]), (0.25, True, "Music volume"))
        self.assertEqual((prefs["Fx"]["value"], prefs["Fx"]["stored"]), (1.0, False))
        companion = self.service.resources.catalog.list("companions")[0]["item_id"]
        self.service.resources.grant(ACCOUNT, "companions", companion)
        self.command("resources/select", {"kind": "companions", "item_id": companion})
        resources = self.read("/resources")
        self.assertTrue(resources["items"][0]["equipped"])
        self.assertEqual(resources["equipped"]["companion"]["item_id"], companion)
        self.assertEqual(self.read()["equipped"]["companion_revision"], 1)
        self.assertEqual(self.read("/consumables")["total"], 0)

    def test_social_housing_and_position_sections(self):
        self.store.accept_friendship(ACCOUNT, FRIEND)
        with self.db:
            self.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (ACCOUNT, "Fixture Friend", "StandaloneWindows", "favorite"))
            self.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (ACCOUNT, "Stranger", "PS4", "block"))
        social = self.read("/social")
        friend = next(r for r in social["items"] if r["target"] == "Fixture Friend")
        self.assertEqual((friend["target_account_id"], friend["is_favorite"], friend["mutual_friend"]), (FRIEND, True, True))
        blocked = self.read("/social", {"kind": "block"})["items"]
        self.assertEqual([(r["target"], r["target_account_id"]) for r in blocked], [("Stranger", None)])
        incoming = self.read("/social", {"direction": "incoming"})["items"]
        self.assertEqual(incoming[0]["target_account_id"], FRIEND)
        self.error(400, self.read, "/social", {"direction": "sideways"})
        binding, item, _other = self.home()
        spaces = self.read("/housing")
        self.assertEqual((spaces["items"][0]["space_label"], spaces["items"][0]["placed_count"]), ("Home", 3))
        detail = self.read("/housing/" + binding["instance_id"])
        self.assertEqual(detail["items"][0]["position"], {"x": 1.0, "y": 0.0, "z": 4.0})
        self.assertTrue(all(i["catalog_known"] for i in detail["items"]))
        self.assertEqual(self.read("/items", {"kind": "housing"})["items"][0]["placed_in"], ["Home"])
        self.error(404, self.read, "/housing/apt-unknown")
        with self.db:
            self.db.execute("INSERT INTO positions VALUES(?,?,?,?,?)", (ACCOUNT, 5.0, 6.0, 7.0, time.time()))
        position = self.read("/position")
        self.assertEqual((position["source"], position["position"]["x"]), ("saved", 5.0))
        self.assertEqual(len(position["preset_positions"]), 2)

    def test_wardrobe_revoke_unequips_presets_and_protects_starters(self):
        self.wear_extra()
        result = self.command("items/revoke", {"kind": "wardrobe", "item_id": self.extra["item_id"]})
        self.assertTrue(result["changed"])
        self.assertEqual(result["after"]["unequipped_from_presets"], ["Default"])
        self.assertTrue(result["after"]["applies_on_next_login"])
        row = self.db.execute("SELECT * FROM presets WHERE ps4_id=? AND name='Default' AND gender='MALE'", (ACCOUNT,)).fetchone()
        self.assertEqual(json.loads(row["preset_json"])["item6"], "null")
        self.assertNotIn(self.extra["item_id"], json.loads(row["assets_json"])["data"])
        self.assertEqual(len(json.loads(row["assets_json"])["data"].split("!")), 2 * len(self.starter))
        self.assertFalse(self.db.execute("SELECT 1 FROM entitlements WHERE ps4_id=? AND item_id=?", (ACCOUNT, self.extra["item_id"])).fetchone())
        self.error(404, self.command, "items/revoke", {"kind": "wardrobe", "item_id": self.extra["item_id"]})
        self.error(409, self.command, "items/revoke", {"kind": "wardrobe", "item_id": next(iter(self.starter)), "gender": "MALE"})
        self.error(400, self.command, "items/revoke", {"kind": "companions", "item_id": "x", "gender": "MALE"})

    def test_resource_and_housing_revoke_clear_selection_and_layouts(self):
        companion = self.service.resources.catalog.list("companions")[0]["item_id"]
        self.service.resources.grant(ACCOUNT, "companions", companion)
        self.command("resources/select", {"kind": "companions", "item_id": companion})
        result = self.command("items/revoke", {"kind": "companions", "item_id": companion})
        self.assertTrue(result["after"]["unequipped"])
        self.assertEqual(self.selection.selected(ACCOUNT, "companions"), ("", 2))
        binding, item, other = self.home()
        result = self.command("items/revoke", {"kind": "housing", "item_id": item})
        self.assertEqual(result["after"]["removed_from_layouts"][0]["removed"], 2)
        layout = json.loads(self.db.execute("SELECT layout_json FROM housing_layouts WHERE instance_id=?", (binding["instance_id"],)).fetchone()[0])
        self.assertEqual((layout["aidasset"], layout["aidasset_tx"], layout["aidasset_r"]), ([other], [2.0], [0.0]))
        self.assertEqual(self.service.housing.load(binding)["aidasset"], [other])

    def test_preset_delete_select_and_rename(self):
        self.error(409, self.command, "presets/delete", {"name": "Default", "gender": "MALE"})
        self.second_preset()
        result = self.command("presets/select", {"name": "Default", "gender": "MALE"})
        self.assertEqual((result["before"]["selected_preset"], result["after"]["selected_preset"]), ("Party", "Default"))
        self.assertFalse(self.command("presets/select", {"name": "Default", "gender": "MALE"})["changed"])
        self.command("presets/select", {"name": "Default", "gender": "FEMALE", "activate_gender": True})
        self.assertEqual(self.manager.profile(ACCOUNT)["gender"], "FEMALE")
        self.error(409, self.command, "presets/rename", {"name": "Default", "gender": "MALE", "new_name": "Party"})
        self.error(400, self.command, "presets/rename", {"name": "Default", "gender": "MALE", "new_name": "Bad#Name"})
        renamed = self.command("presets/rename", {"name": "Default", "gender": "MALE", "new_name": "Casual"})
        self.assertEqual(renamed["after"]["selected_preset"], "Casual")
        self.assertEqual(self.store.preset(ACCOUNT, "MALE")["preset"]["presetname"], "Casual")
        deleted = self.command("presets/delete", {"name": "Casual", "gender": "MALE"})
        self.assertEqual((deleted["after"]["presets"], deleted["after"]["selected_preset"]), (["Party"], "Party"))
        self.error(404, self.command, "presets/delete", {"name": "Casual", "gender": "MALE"})

    def test_preference_updates_are_type_checked_and_resettable(self):
        result = self.command("preferences/set", {"key": "ChatFontSize", "value": 24})
        self.assertEqual((result["before"]["value"], result["after"]["value"]), (20.0, 24.0))
        self.assertEqual(self.store.preferences(ACCOUNT)["ChatFontSize"], 24.0)
        self.command("preferences/set", {"key": "InvertYAxis", "value": True})
        self.assertEqual(self.store.preferences(ACCOUNT)["InvertYAxis"], 1)
        self.command("preferences/set", {"key": "status", "value": "Away for tea"})
        for body in ({"key": "Music", "value": 2.0}, {"key": "InvertYAxis", "value": 2}, {"key": "status", "value": "a#b"},
                     {"key": "mood", "value": 3}, {"key": "Unknown", "value": 1}, {"key": "Music"},
                     {"key": "Music", "value": 0.5, "extra": 1}):
            self.error(400, self.command, "preferences/set", body)
        reset = self.command("preferences/set", {"key": "ChatFontSize", "value": None})
        self.assertEqual(reset["after"], {"key": "ChatFontSize", "value": 20.0, "stored": False, "applies_on_next_login": True})

    def test_social_removal_is_symmetric_for_friends_only(self):
        self.store.accept_friendship(ACCOUNT, FRIEND)
        with self.db:
            self.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (ACCOUNT, "Fixture Friend", "StandaloneWindows", "favorite"))
            self.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (FRIEND, "Fixture Player", "StandaloneWindows", "block"))
            self.db.execute("INSERT INTO relations VALUES(?,?,?,?)", (ACCOUNT, "Stranger", "PS4", "block"))
        result = self.command("social/remove", {"kind": "friend", "target": "Fixture Friend", "platform": "StandaloneWindows"})
        self.assertEqual((result["before"]["relations"], result["after"]["relations"]), (["favorite", "friend"], []))
        self.assertEqual(result["after"]["their_relations"], ["block"])  # other account's own block is untouched
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM friend_events WHERE operation='remove_friendship'").fetchone()[0], 1)
        self.command("social/remove", {"kind": "block", "target": "Stranger", "platform": "PS4"})
        self.assertFalse(self.db.execute("SELECT 1 FROM relations WHERE ps4_id=?", (ACCOUNT,)).fetchone())
        self.error(404, self.command, "social/remove", {"kind": "block", "target": "Stranger", "platform": "PS4"})
        self.error(400, self.command, "social/remove", {"kind": "block", "target": "Stranger", "platform": "Xbox"})

    def test_position_and_layout_resets(self):
        with self.db:
            self.db.execute("INSERT INTO positions VALUES(?,?,?,?,?)", (ACCOUNT, 5.0, 6.0, 7.0, time.time()))
            self.db.execute("UPDATE presets SET position_json=? WHERE ps4_id=? AND gender='MALE'",
                            (json_field({"GUID": "", "PS4ID": ACCOUNT, "lastPosition_x": 9.0, "lastPosition_y": 0.0, "lastPosition_z": 1.0}), ACCOUNT))
        result = self.command("position/reset", {})
        self.assertEqual(result["after"]["preset_positions_reset"], ["Default/MALE"])
        self.assertEqual(self.read("/position")["source"], "default")
        self.assertFalse(self.command("position/reset", {})["changed"])
        binding, _item, _other = self.home()
        with self.db:
            self.db.execute("INSERT INTO housing_save_stages VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (binding["instance_id"], "g" * 32, ACCOUNT, "b", "{}", None, None, "open", time.time(), time.time() + 30))
        self.error(409, self.command, "housing/reset-layout", {"instance_id": binding["instance_id"]})
        with self.db:
            self.db.execute("DELETE FROM housing_save_stages")
        result = self.command("housing/reset-layout", {"instance_id": binding["instance_id"]})
        self.assertEqual((result["before"]["placed_count"], result["after"]["placed_count"]), (3, 0))
        self.assertEqual(self.service.housing.load(binding)["aidasset"], [])
        self.assertFalse(self.command("housing/reset-layout", {"instance_id": binding["instance_id"]})["changed"])
        self.error(404, self.command, "housing/reset-layout", {"instance_id": "apt-unknown"})

    def test_permissions_routes_audit_and_idempotent_replay(self):
        self.second_preset()
        self.error(403, self.command, "presets/select", {"name": "Default", "gender": "MALE"}, role="moderator")
        self.error(404, self.command, "presets/explode", {"name": "Default", "gender": "MALE"})
        self.error(400, self.command, "presets/select", {"name": "Default", "gender": "MALE", "surprise": 1})
        first = self.command("presets/select", {"name": "Default", "gender": "MALE"}, role="owner", key="same-character-key")
        replay = self.command("presets/select", {"name": "Default", "gender": "MALE"}, role="owner", key="same-character-key")
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["audit_id"], replay["audit_id"])
        audit = self.db.execute("SELECT * FROM management_audit WHERE audit_id=?", (first["audit_id"],)).fetchone()
        self.assertEqual((audit["operation"], audit["target_id"], audit["actor_id"]), ("players.data", ACCOUNT, "owner"))
        self.assertEqual(json.loads(audit["after_json"])["selected_preset"], "Default")
        history = self.manager.read("users/" + ACCOUNT + "/audit", {}, self.manager.actor(self.headers(), "read"))
        self.assertEqual(history["items"][0]["operation"], "players.data")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM management_audit WHERE operation='players.data'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
