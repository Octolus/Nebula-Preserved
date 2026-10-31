"""Offline reconstruction checks. No sockets, game process or listener."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "tools"))

from avatar_entry_codec import decode_flat_preset, encode_entry_fields, encode_value_texts
from housing import HOUSING_FIELDS, PERSONAL_SPACE_SCENES
from service import Service
from state import Catalog, Store
from wire import KEY, ProtocolError, Request, decrypt, encrypt, json_field, session_guid


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.schemas = json.loads((ROOT / "protocol/bootstrap-response-contracts.json").read_text(encoding="utf-8"))
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-tests"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.no_network = patch.object(socket, "socket", side_effect=AssertionError("Network is forbidden in offline checks"))
        self.no_network.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        self.guid = self.login("offline-account-a", "Display Name")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def call(self, route, *fields):
        return self.service.dispatch(route, "#".join(fields) + "#StandaloneWindows")

    def login(self, account, username):
        response = self.call("N2UserExist", username, "v72", "false", account, "1.25")
        # Independent native acceptance condition: response0 is PS4ID, not name;
        # the 7 fields and trailing empty ban fields are required.
        fields = response.split("#")
        self.assertEqual(fields[0], account)
        self.assertEqual(len(fields), 7)
        self.assertEqual(fields[4:], ["false", "", ""])
        h = "a" * 64
        self.assertEqual(self.call("ChannelGUIDServlet", account, h), "true#")
        return session_guid(account, h)

    def test_crypto_and_json_delimiter(self):
        self.assertEqual(KEY.hex(), "f794fdd76962dfc07ba2efa75c7cf887")
        text = "13#example#Nexus#1#hello#0"
        self.assertEqual(decrypt(encrypt(text)), text)
        field = json_field({"status": "hello#world", "face": "\U0001f600"})
        self.assertNotIn("#", field)
        self.assertEqual(json.loads(field)["status"], "hello#world")

    def test_bootstrap_distinct_response_shapes(self):
        steam = self.call("STMGetUserInfo", "", "offline-account-a").split("#")
        self.assertEqual(json.loads(steam[1][:-1])["response"]["result"], "OK")
        self.assertEqual(self.call("CheckerServlet", "Name", "", "", "4.125").split("#"), ["OK", "4.125", "false", "", ""])
        self.assertEqual(self.call("CheckServerStatusServlet", "Name", "4.125"), "true#Name#4.125#1")
        self.assertEqual(self.call("GetIinitInfosNeededServlet", self.guid, "offline-account-a").split("#")[0], self.guid)
        cinema = self.call("GetCinemaFilmsServlet", self.guid, "offline-account-a").split("#")
        self.assertEqual(len(cinema), 7)
        self.assertEqual(cinema[0], self.guid)
        self.assertTrue(all(x.isdigit() for x in cinema[1:5]))

    def test_cinema_no_films_terminates_native_schedule_without_media(self):
        fields = self.call("GetCinemaFilmsServlet", self.guid, "offline-account-a").split("#")
        self.assertEqual(fields[5:], ["LOCAL_NO_FILMS", "84600"])
        # Independent acceptance predicates recovered from 0x5568b0:
        # at least one complete pair must advance the non-null-list loop;
        # Add executes only before the day boundary, return after 86399.
        pairs = fields[5:]
        self.assertGreater(len(pairs), 0)
        self.assertEqual(len(pairs) % 2, 0)
        elapsed = 0
        scheduled_names = []
        for name, duration in zip(pairs[::2], pairs[1::2]):
            next_second = elapsed + 1800 + int(duration)
            self.assertLessEqual(next_second, 2147483647)
            if next_second < 86400:
                scheduled_names.append(name)
            elapsed = next_second
        self.assertGreater(elapsed, 86399, "Native loop must exit after the first pair")
        self.assertEqual(scheduled_names, [], "Sentinel must never reach the MP4 loader")

    def test_owned_inventory_names_and_idempotence(self):
        response = self.call("GetPurchases", self.guid).split("#")
        data = json.loads(response[2])
        self.assertEqual(response[:2], ["true", self.guid])
        self.assertEqual(len(data["cloths"]), 11)
        self.assertEqual(len(data["cloths"]), len(data["clothsName"]))
        item = self.catalog.resolve(data["cloths"][0])
        self.store.grant("offline-account-a", item)
        self.assertEqual(len(self.store.inventory("offline-account-a")), 11)
        with self.assertRaises(ProtocolError):
            self.catalog.resolve("fabricated-id")

    def test_wardrobe_empty_and_view_status_mapping(self):
        empty = self.call("GetInfoServlet", "0", self.guid, "offline-account-a", "0", "not-a-category", "0")
        self.assertEqual(empty, "true!" + self.guid + "!!!!!MALE")
        items = self.call("GetInfoServlet", "0", self.guid, "offline-account-a", "0", "CLOTH_BODY_TORSO", "0").split("!")
        self.assertEqual(len(items), 7)
        self.assertTrue(items[2])
        self.assertEqual(items[3], "1")
        self.assertEqual(items[5], "1")
        item_id = items[2]
        self.call("WardrobeOptionItemServlet", self.guid, "offline-account-a", item_id, "2")
        self.assertEqual(self.call("GetInfoServlet", "0", self.guid, "offline-account-a", "0", "CLOTH_BODY_TORSO", "0"), empty)
        stored = self.call("GetInfoServlet", "0", self.guid, "offline-account-a", "0", "CLOTH_BODY_TORSO", "1").split("!")
        self.assertEqual(stored[2:4], [item_id, "2"])
        self.call("WardrobeOptionItemServlet", self.guid, "offline-account-a", item_id, "0")
        favorite = self.call("GetInfoServlet", "0", self.guid, "offline-account-a", "0", "CLOTH_BODY_TORSO", "0").split("!")
        self.assertEqual(favorite[3], "0")

    def test_remote_avatar_echo_and_all_fields(self):
        remote = self.login("offline-account-b", "Other Player")
        for numeric, gender, count in (("0", "MALE", 450), ("1", "FEMALE", 462)):
            fields = self.call("GetLastUsedPreset", self.guid, "offline-account-a", remote, numeric).split("#")
            self.assertEqual(len(fields), 6)
            self.assertEqual(fields[:3], ["true", "offline-account-a", gender])
            self.assertEqual(len(json.loads(fields[3])), count)
            halves = json.loads(fields[4])["data"].split("!")
            self.assertEqual(len(halves) % 2, 0)
            self.assertTrue(all(x.startswith("CLOTH_") for x in halves[len(halves)//2:]))
            self.assertEqual(json.loads(fields[5])["GUID"], remote)

    def test_customization_save_codec_and_persistence(self):
        preset = self.store.preset("offline-account-a", "MALE")["preset"]
        preset["presetname"] = "Hash # inside serialized field \U0001f600"
        fields = next(x for x in self.schemas["json_and_enum_declarations"] if x["name"] == "JsonClasses.PresetMaleJson")["fields"]
        tokens = [str(preset[x["name"]]) if preset[x["name"]] is not None else None for x in fields]
        serialized = encode_value_texts(tokens)
        self.assertEqual(self.call("N2SavePreset", self.guid, "offline-account-a", "Custom", "0", serialized), "true#true")
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        saved = self.store.preset("offline-account-a", "MALE", "Custom")
        self.assertEqual(saved["preset"]["presetname"], "Custom")
        self.assertEqual(len(saved["preset"]), 450)
        self.assertIn("#Custom", self.call("ShowPresetsServlet", self.guid, "offline-account-a", "0"))
        self.call("RenamePresetServlet", self.guid, "offline-account-a", "Custom", "Renamed", "0")
        self.assertEqual(self.store.preset("offline-account-a", "MALE")["preset"]["presetname"], "Renamed")
        self.call("RemovePresetServlet", self.guid, "offline-account-a", "Renamed", "Renamed", "0")
        with self.assertRaises(ProtocolError):
            self.store.preset("offline-account-a", "MALE", "Renamed")

    def test_preferences_color_and_wardrobe_five_fields(self):
        self.call("SavePlayerPref", self.guid, "NameColorSelectedIndex", '{"x":0.2,"y":0.3,"z":0.4}')
        prefs = json.loads(self.call("GetPlayerPrefsServlet", self.guid, "offline-account-a").split("#")[2])
        self.assertEqual([prefs["NameColorSelectedIndex_" + x] for x in "rgb"], [0.2, 0.3, 0.4])
        check = self.call("Send_CheckIsInWardrobeServlet", self.guid, "offline-account-a", self.guid).split("#")
        self.assertEqual(check, ["OK", self.guid, "", "false", ""])
        with self.assertRaises(ProtocolError):
            self.call("SavePlayerPref", self.guid, "MasterVolume", "NaN")

    def test_sessions_ownership_and_unknowns_fail(self):
        remote = self.login("offline-account-b", "Other")
        with self.assertRaises(ProtocolError) as error:
            self.call("GetPlayerPrefsServlet", remote, "offline-account-a")
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(ProtocolError) as error:
            self.call("UnreconstructedRoute", self.guid)
        self.assertEqual(error.exception.status, 501)
        with self.assertRaises(ProtocolError):
            Request.parse(self.guid + "#unknown-platform")

    def test_snapshot_bindings(self):
        self.store.export_instance_accounts(self.path)
        snapshot = json.loads((self.path / "instance-accounts.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["format_version"], 1)
        self.assertEqual(snapshot["accounts"][0]["guid"], self.guid)
        self.assertEqual(snapshot["accounts"][0]["ps4_id"], "offline-account-a")

    def test_per_gender_selection_and_explicit_item_metadata(self):
        male = self.store.preset("offline-account-a", "MALE")
        self.store.save_preset("offline-account-a", "MaleOnly", "MALE", male["preset"], male["assets"], male["position"])
        self.assertEqual(self.store.preset("offline-account-a", "FEMALE")["name"], "Default")
        self.call("RenamePresetServlet", self.guid, "offline-account-a", "MaleOnly", "MaleRenamed", "0")
        self.assertEqual(self.store.preset("offline-account-a", "MALE")["name"], "MaleRenamed")
        self.assertEqual(self.store.preset("offline-account-a", "FEMALE")["name"], "Default")
        first = self.store.inventory("offline-account-a")[0]
        item = self.catalog.resolve(first["item_id"], first["gender"], first["category"])
        self.store.grant("offline-account-a", item, "Local editable item", 2)
        updated = next(x for x in self.store.inventory("offline-account-a") if x["item_id"] == first["item_id"])
        self.assertEqual((updated["display_name"], updated["item_type"]), ("Local editable item", 2))

    def descriptor(self, complete):
        data = {"format_version": 1, "protocol_complete": complete, "listening": True,
                "heartbeat": time.time(), "ip": "127.0.0.1", "port": 28000,
                "instance_id": "offline-instance", "psidglobal": "Nexus",
                "maxusers": 32, "players": 0}
        (self.path / "instance-status.json").write_text(json.dumps(data), encoding="utf-8")
        return data

    def test_allocation_never_advertises_incomplete_or_stale_instance(self):
        self.descriptor(False)  # synthetic file only; no server is listening
        with self.assertRaises(ProtocolError) as error:
            self.call("N2LoadSpace", self.guid, "offline-account-a", "Nexus", "false", "", "")
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(self.call("N2SpaceLoading", self.guid, "offline-account-a"), self.guid + "#false")
        data = self.descriptor(True)  # test-only acceptance fixture
        self.assertEqual(self.call("N2LoadSpace", self.guid, "offline-account-a", "Nexus", "false", "", ""), self.guid + "#false#false")
        self.assertEqual(self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#"), [self.guid, "true", "offline-instance", "Nexus", "127.0.0.1", "28000"])
        data["heartbeat"] -= 60
        (self.path / "instance-status.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.call("N2SpaceLoading", self.guid, "offline-account-a"), self.guid + "#false")

    def test_login_alias_multi_instance_selection_and_fresh_poll_endpoint(self):
        def instance(instance_id, scene, port, players):
            value = {"format_version": 1, "protocol_complete": True, "listening": True,
                     "heartbeat": time.time(), "ip": "127.0.0.1", "port": port,
                     "instance_id": instance_id, "psidglobal": scene,
                     "maxusers": 32, "players": players}
            folder = self.path / "instances" / instance_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "instance-status.json").write_text(json.dumps(value), encoding="utf-8")
            return value, folder

        nexus_a, nexus_a_folder = instance("nexus-a", "Nexus", 28001, 4)
        instance("nexus-b", "Nexus", 28002, 1)
        instance("leaf-a", "LeafPark", 28003, 0)
        # Native login asks for literal Login; local routing selects the least
        # populated actual Nexus instance and field3 remains its scene key.
        self.call("N2LoadSpace", self.guid, "offline-account-a", "Login", "false", "", "")
        loaded = self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#")
        self.assertEqual(loaded[2:6], ["nexus-b", "Nexus", "127.0.0.1", "28002"])
        # Exclusion selects the other ready instance for the same scene.
        self.call("N2LoadSpace", self.guid, "offline-account-a", "Nexus", "false", "nexus-b", "")
        loaded = self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#")
        self.assertEqual(loaded[2:4], ["nexus-a", "Nexus"])
        # Polling uses the fresh validated descriptor, not the allocation-time
        # endpoint, after a loopback instance restart.
        nexus_a["port"] = 28004
        nexus_a["heartbeat"] = time.time()
        (nexus_a_folder / "instance-status.json").write_text(json.dumps(nexus_a), encoding="utf-8")
        self.assertEqual(self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#")[4:],
                         ["127.0.0.1", "28004"])

    def test_wardrobe_numeric_state_json_members_and_corrected_client_loop(self):
        remote = self.login("offline-account-b", "Other")
        self.descriptor(True)
        for guid, account in ((self.guid, "offline-account-a"), (remote, "offline-account-b")):
            self.call("N2LoadSpace", guid, account, "Nexus", "false", "", "")
        self.call("SetUserInWardrobe", remote, "offline-instance", "1", "FEMALE", "Other", "Ready", "0", "0.1", "0.2", "0.3", "4", "5", "6")
        fields = self.call("GetAllInWardrobe", self.guid, "offline-instance").split("#")
        self.assertEqual(len(fields), 2)
        output = [None] * (len(fields) - 1)
        # Native loop with documented JGE->JG fix, indexes1..M inclusive.
        for i in range(1, len(output) + 1):
            output[i - 1] = fields[i]
        label = json.loads(output[0])
        self.assertEqual((label["GUID"], label["gender"]), (remote, "FEMALE"))
        self.assertEqual([label["lastPosX"], label["lastPosY"], label["lastPosZ"]], [4, 5, 6])
        self.assertFalse(fields[-1] == "")

    def friend_event(self, operation, actor, other, created_at=None, event_id=None):
        event_id = event_id or str(uuid.uuid4())
        directory = self.path / "friend-events"
        directory.mkdir(exist_ok=True)
        value = {"format_version": 1, "event_id": event_id, "operation": operation,
                 "actor_ps4_id": actor, "other_ps4_id": other,
                 "created_at": time.time() if created_at is None else created_at,
                 "policy": "correlated_online_request_v1"}
        (directory / (event_id + ".json")).write_text(json.dumps(value), encoding="utf-8")
        return value

    def presence(self, players, generation=None):
        value = {"format_version": 1, "generation": time.time() if generation is None else generation,
                 "players": [{"guid": guid, "status": status} for guid, status in players]}
        (self.path / "instance-presence.json").write_text(json.dumps(value), encoding="utf-8")

    def test_distinct_social_shapes_and_native_entrydata_golden(self):
        other = self.login("offline-account-b", "Other")
        self.assertEqual(self.call("N2GetSocialList", self.guid, "offline-account-a", "0", "1"), "true#" + self.guid + "#1#0")
        self.friend_event("accept_friendship", "offline-account-a", "offline-account-b")
        result = self.call("N2GetSocialList", self.guid, "offline-account-a", "0", "1").split("#")
        self.assertEqual(result[:4], ["true", self.guid, "1", "1"])
        # Native public order is bool,status enum,name,platform int,list enum.
        # Each prefix is UTF16 length+0x24; private EntryData.textIndex is absent.
        self.assertEqual(result[4], ")False+Offline)Other%1+Friends")
        modern = self.call("GetSocialList", self.guid, "0").split("#")
        self.assertEqual(len(modern), 2)
        self.assertEqual(json.loads(modern[1]), {"lUsernames": ["Other"]})
        reciprocal = self.call("N2GetSocialList", other, "offline-account-b", "0", "0").split("#")
        self.assertEqual(reciprocal[2:4], ["0", "1"])
        self.assertIn("Display Name", reciprocal[4])
        for kind in ("3", "4", "7"):
            with self.assertRaises(ProtocolError) as error:
                self.call("N2GetSocialList", self.guid, "offline-account-a", kind, "1")
            self.assertEqual(error.exception.status, 501)

    def test_social_membership_favorite_status_and_relation_codes(self):
        other = self.login("offline-account-b", "Other\U0001f600")
        self.store.accept_friendship("offline-account-a", "offline-account-b")
        self.call("N2ToggleFavorite", self.guid, "Other\U0001f600", "1")
        self.presence([(other, 3)])
        fields = self.call("N2GetSocialList", self.guid, "offline-account-a", "0", "1").split("#")
        self.assertEqual(fields[4], "(True,Wardrobe+Other\U0001f600%1+Friends")
        self.assertEqual(self.call("N2GetRelationship", self.guid, "offline-account-a", other).split("#"), ["OK", "", "", "", "2"])
        self.call("N2AddSilenced", self.guid, "Other\U0001f600", "1")
        self.assertEqual(self.call("N2GetRelationship", self.guid, "offline-account-a", other).split("#")[4], "3")
        self.assertEqual(self.call("N2GetRelationship", other, "offline-account-b", self.guid).split("#")[4], "4")
        self.assertEqual(self.call("N2GetSocialList", self.guid, "offline-account-a", "1", "1").split("#")[3], "1")
        self.call("N2AddBlock", self.guid, "Other\U0001f600", "1")
        self.assertEqual(self.call("N2GetRelationship", self.guid, "offline-account-a", other).split("#")[4], "5")
        self.assertEqual(self.call("N2GetRelationship", other, "offline-account-b", self.guid).split("#")[4], "6")
        self.presence([(other, 0)], generation=time.time() - 30)
        self.assertIn("+Offline", self.call("N2GetSocialList", self.guid, "offline-account-a", "0", "1"))
        self.call("N2RemoveFriend", self.guid, "Other\U0001f600", "1")
        for guid, account in ((self.guid, "offline-account-a"), (other, "offline-account-b")):
            self.assertEqual(self.call("N2GetSocialList", guid, account, "0", "1").split("#")[3], "0")
        self.assertNotIn("favorite", self.store.relation_kinds("offline-account-a", "Other\U0001f600", "1"))

    def test_account_rename_migrates_all_inbound_social_identity_rows(self):
        other = self.login("offline-account-b", "Other")
        self.store.accept_friendship("offline-account-a", "offline-account-b")
        self.call("N2ToggleFavorite", self.guid, "Other", "1")
        self.call("N2AddSilenced", self.guid, "Other", "1")
        self.call("N2AddBlock", self.guid, "Other", "1")

        # Exercise both mutable native identity components: display name and
        # platform correction must move the same relation rows together.
        self.store.account("offline-account-b", "Renamed", "PS4")

        self.assertEqual(
            self.store.relation_kinds("offline-account-a", "Renamed", "0"),
            {"friend", "favorite", "silenced", "block"},
        )
        self.assertEqual(self.store.relation_kinds("offline-account-a", "Other", "1"), set())
        # The renamed account's reciprocal owner-side friendship is unchanged.
        self.assertEqual(
            self.store.relation_kinds("offline-account-b", "Display Name", "1"),
            {"friend"},
        )
        for list_type in ("0", "1", "2"):
            fields = self.call("N2GetSocialList", self.guid, "offline-account-a", list_type, "1").split("#")
            self.assertEqual(fields[3], "1")
            self.assertIn("+Renamed%0", fields[4])
            self.assertNotIn("Other", fields[4])
        self.assertEqual(
            self.call("N2GetRelationship", self.guid, "offline-account-a", other).split("#")[4],
            "5",
        )

    def test_account_identity_migration_rejects_profile_collision(self):
        self.login("offline-account-b", "Other")
        self.store.accept_friendship("offline-account-a", "offline-account-b")
        before = [tuple(row) for row in self.store.db.execute(
            "SELECT ps4_id,target,target_platform,kind FROM relations ORDER BY ps4_id,target,kind"
        )]

        with self.assertRaises(ProtocolError) as error:
            self.store.account("offline-account-b", "Display Name", "StandaloneWindows")

        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.store.account("offline-account-b")["username"], "Other")
        after = [tuple(row) for row in self.store.db.execute(
            "SELECT ps4_id,target,target_platform,kind FROM relations ORDER BY ps4_id,target,kind"
        )]
        self.assertEqual(after, before)

        # An already-ambiguous old identity cannot be reassigned safely: the
        # target rows do not carry a ps4_id that could disambiguate ownership.
        self.store.account("offline-account-c", "Other", "StandaloneWindows")
        with self.assertRaises(ProtocolError) as error:
            self.store.account("offline-account-b", "Unique", "StandaloneWindows")
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.store.account("offline-account-b")["username"], "Other")

    def test_friend_outbox_idempotence_ordering_and_snapshot_compatibility(self):
        self.login("offline-account-b", "Other")
        # File UUID order differs from event time order. Late replay must not
        # resurrect a removed friendship, including after restarting SQLite.
        self.friend_event("accept_friendship", "offline-account-a", "offline-account-b", 1000, "ffffffff-ffff-4fff-8fff-ffffffffffff")
        self.friend_event("remove_friendship", "offline-account-b", "offline-account-a", 1001, "00000000-0000-4000-8000-000000000001")
        first = self.store.import_friend_events()
        self.assertEqual(first["applied"], 2)
        self.assertEqual(self.store.import_friend_events()["applied"], 0)
        self.friend_event("accept_friendship", "offline-account-a", "offline-account-b", 999)
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        self.store.import_friend_events()
        self.assertNotIn("friend", self.store.relation_kinds("offline-account-a", "Other", "1"))
        self.friend_event("accept_friendship", "offline-account-a", "offline-account-b", 1002)
        self.store.export_instance_accounts(self.path)
        accounts = json.loads((self.path / "instance-accounts.json").read_text())
        relations = json.loads((self.path / "instance-relations.json").read_text())
        self.assertEqual(accounts["format_version"], 1)
        self.assertEqual(len(accounts["accounts"]), 2)
        self.assertEqual(relations["format_version"], 1)
        self.assertEqual(len(relations["relations"]), 2)
        self.assertEqual({x["target_platform"] for x in relations["relations"]}, {"StandaloneWindows"})
        self.assertFalse(list(self.path.glob("*.tmp")))

    def test_social_lookup_requires_live_instance_and_exact_platform(self):
        other = self.login("offline-account-b", "Other")
        self.assertEqual(self.call("N2GetPsidglobalAndGuidByUsernamePlatform", self.guid, "Other", "1"), "OK##")
        self.descriptor(True)
        self.call("N2LoadSpace", other, "offline-account-b", "Nexus", "false", "", "")
        self.presence([(other, 0)])
        lookup = self.call("N2GetPsidglobalAndGuidByUsernamePlatform", self.guid, "Other", "1").split("#")
        self.assertEqual(lookup, ["OK", "Nexus", other])
        self.assertEqual(self.call("N2GetPsidglobalAndGuidByUsernamePlatform", self.guid, "Other", "0"), "OK##")
        self.store.account("offline-account-c", "Other", "StandaloneWindows")
        with self.assertRaises(ProtocolError) as error:
            self.call("N2GetPsidglobalAndGuidByUsernamePlatform", self.guid, "Other", "1")
        self.assertEqual(error.exception.status, 409)

    def test_old_numeric_relation_migration_and_invalid_friend_event(self):
        self.login("offline-account-b", "Other")
        with self.store.db:
            self.store.db.execute("INSERT INTO relations VALUES(?,?,?,?)", ("offline-account-a", "Other", "1", "block"))
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        self.assertEqual(self.store.relation_kinds("offline-account-a", "Other", "StandaloneWindows"), {"block"})
        event = self.friend_event("accept_friendship", "offline-account-a", "unknown-account")
        self.assertEqual(self.store.import_friend_events()["invalid"], 1)
        self.assertFalse(self.store.db.execute("SELECT 1 FROM friend_events WHERE event_id=?", (event["event_id"],)).fetchone())

    def test_dotnet_guid_n_and_utf8_bom_event_compatibility(self):
        self.login("offline-account-b", "Other")
        event = self.friend_event("accept_friendship", "offline-account-a", "offline-account-b", event_id=uuid.uuid4().hex)
        path = self.path / "friend-events" / (event["event_id"] + ".json")
        path.write_text(json.dumps(event), encoding="utf-8-sig")
        canonical = str(uuid.UUID(event["event_id"]))
        alias = {**event, "event_id": canonical}
        (path.parent / (canonical + ".json")).write_text(json.dumps(alias), encoding="utf-8")
        self.assertEqual(self.store.import_friend_events()["applied"], 1)
        self.assertTrue(self.store.db.execute("SELECT 1 FROM friend_events WHERE event_id=?", (canonical,)).fetchone())
        self.assertEqual(self.store.import_friend_events()["seen"], 2)

    def test_resource_collections_purchases_and_snapshot_share_explicit_grants(self):
        self.assertEqual(self.call("GetCompanionsServlet", self.guid, "offline-account-a"), "true#" + self.guid)
        self.assertEqual(self.call("GetLocomotionsServlet", self.guid, "offline-account-a"), "true#" + self.guid)
        chosen = {}
        for kind in ("companions", "locomotions"):
            row = self.service.resources.catalog.list(kind)[0]
            chosen[kind] = row["item_id"]
            self.service.resources.grant("offline-account-a", kind, row["item_id"], "Local " + kind)
        for route, kind in (("GetCompanionsServlet", "companions"), ("GetLocomotionsServlet", "locomotions")):
            self.assertEqual(self.call(route, self.guid, "offline-account-a").split("#"), ["true", self.guid, chosen[kind]])
        purchases = json.loads(self.call("GetPurchases", self.guid).split("#")[2])
        for kind, item_id in chosen.items():
            self.assertEqual(purchases[kind], [item_id])
            self.assertEqual(purchases[kind + "Name"], ["Local " + kind])
        self.store.export_instance_accounts(self.path)
        account = json.loads((self.path / "instance-accounts.json").read_text())["accounts"][0]
        self.assertEqual(account["companion_ids"], [chosen["companions"]])
        self.assertEqual(account["locomotion_ids"], [chosen["locomotions"]])

    def test_legacy_preset_modes_and_identity_are_distinct(self):
        current = self.call("GetInfoServlet", "1", self.guid, "offline-account-a").split("#")
        self.assertEqual(current[:3], ["true", self.guid, ""])
        self.assertEqual(current[4], "MALE")
        decoded = decode_flat_preset(current[3], "MALE", self.schemas["json_and_enum_declarations"])
        self.assertEqual(decoded["preset"]["iduser"], "offline-account-a")
        last = self.call("GetInfoServlet", "2", self.guid, "offline-account-a", "1").split("#")
        self.assertEqual(last[:2], ["true", self.guid])
        self.assertEqual(last[3], "1")
        self.assertEqual(decode_flat_preset(last[2], "FEMALE", self.schemas["json_and_enum_declarations"])["preset"]["presetname"], "Default")
        named = self.call("GetInfoServlet", "3", self.guid, "offline-account-a", "0", "Default").split("#")
        self.assertEqual(len(named), 4)
        self.assertEqual(json.loads(named[2])["presetname"], "Default")
        self.assertIn("data", json.loads(named[3]))
        result = self.call("UserExistsServlet", "offline-account-a", "v72", "False", "offline-account-a", "1").split("#")
        self.assertEqual(result[0], "offline-account-a")
        self.assertEqual(self.store.session(self.guid)["username"], "Display Name")
        with self.assertRaises(ProtocolError):
            self.call("UserExistsServlet", "wrong", "v72", "False", "offline-account-a", "1")
        self.assertEqual(self.call("InfoServlet", self.guid, "offline-account-a", "opaque"), "true#")

    def test_local_news_complete_pairs_and_reports_are_durable(self):
        fields = self.call("GetNewsServlet", "99").split("#")
        self.assertEqual(len(fields), 1 + 2 * int(fields[0]))
        self.assertIn("preservation", fields[1].lower())
        # Native loops ALL remaining pairs and reverse-creates array entries.
        pairs = [(fields[i], fields[i + 1]) for i in range(1, len(fields), 2)]
        self.assertEqual(len(pairs), int(fields[0]))
        with self.assertRaises(ProtocolError):
            self.call("GetNewsServlet", "100")
        first = self.call("ReportServlet", self.guid, "offline-account-a", "0", "Other", "Local issue").split("#")
        second = self.call("ReportServlet", self.guid, "offline-account-a", "0", "Other", "Local issue").split("#")
        self.assertEqual(first, ["true", self.guid, "offline-account-a", "true"])
        self.assertEqual(second[-1], "false")
        self.assertEqual(self.call("checkStateNPFriendsServlet", self.guid, "offline-account-a", "Unknown"), "true#" + self.guid)

    def private_instance(self, instance_id="home-a", scene="Home"):
        data = {**self.descriptor(True), "instance_id": instance_id, "psidglobal": scene, "port": 28001}
        folder = self.path / "instances" / instance_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "instance-status.json").write_text(json.dumps(data), encoding="utf-8")
        (self.path / "instance-status.json").unlink()
        self.service.housing.bind_space(instance_id, scene, "offline-account-a", "Home")
        self.call("N2LoadSpace", self.guid, "offline-account-a", "Home", "true", "", "")
        return data, folder

    def test_personal_space_binding_and_empty_layout_are_exact(self):
        with self.assertRaises(ProtocolError):
            self.call("N2LoadSpace", self.guid, "offline-account-a", "Home", "true", "", "")
        with self.assertRaises(ProtocolError) as error:
            self.service.housing.bind_space("invented-home", "VerifiedHomeScene", "offline-account-a", "Home")
        self.assertEqual(error.exception.status, 409)
        self.private_instance(scene="Home")
        self.assertEqual(self.call("GetPersonalSpacesServlet", self.guid, "offline-account-a").split("#"), ["true", self.guid, "offline-account-a", "Home"])
        loaded = self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#")
        self.assertEqual(loaded[2:4], ["home-a", "Home"])
        fields = self.call("HousingReadPresetServlet", self.guid, "offline-account-a", "Home").split("#")
        self.assertEqual(len(fields), 5)
        self.assertEqual(fields[4], self.guid)
        layout = json.loads(fields[3])
        self.assertEqual(layout["psidglobal"], "Home")
        self.assertTrue(all(layout[field["name"]] == [] for field in HOUSING_FIELDS[1:]))
        self.assertEqual(self.call("N2HousingReadPreset", self.guid, "offline-account-a", "Home").split("#"), fields)
        empty_items = self.call("GetHousingTypeServlet", self.guid, "offline-account-a", "1").split("#")
        self.assertEqual(empty_items, ["true", self.guid, "offline-account-a", "1"])
        with self.assertRaises(ProtocolError):
            self.service.housing.bind_space("home-a", "AnotherScene", "offline-account-a", "Home")

    def test_housing_binding_export_is_exact_read_only_and_account_owned(self):
        with self.assertRaises(ProtocolError) as error:
            self.service.housing.bind_space("orphan-home", "Home", "missing-account", "Home")
        self.assertEqual(error.exception.status, 404)
        self.private_instance()
        before = self.store.db.total_changes
        path = self.service.housing.export_bindings(self.path)
        self.assertEqual(self.store.db.total_changes, before)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(snapshot), {"format_version", "generation", "bindings"})
        self.assertEqual(snapshot["format_version"], 1)
        self.assertIsInstance(snapshot["generation"], float)
        self.assertEqual(snapshot["bindings"], [{
            "instance_id": "home-a", "psidglobal": "Home",
            "owner_ps4_id": "offline-account-a", "logical_space_key": "Home",
        }])
        self.assertEqual(PERSONAL_SPACE_SCENES["SorcerersEyrie"], "SorcerersEyrie1")

    def housing_part(self, ids, part, walls=(), ceilings=()):
        value = {field["name"]: [] for field in HOUSING_FIELDS}
        value.update(psidglobal="Home", atablename=None)
        value["aidasset"] = [item if (i < 100) == (part == "0") else "null" for i, item in enumerate(ids)]
        for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
            value[key] = [str(i + 1) if (i < 100) == (part == "0") else "0" for i in range(len(ids))]
        value["aidassetWall"], value["aidassetWallSlot"] = list(walls), list(range(len(walls)))
        value["aidassetCeiling"], value["aidassetCeilingSlot"] = list(ceilings), list(range(len(ceilings)))
        return value

    def test_housing_sparse_parts_reverse_order_durable_grants_and_table_order(self):
        from housing_atomic import ACK_SECONDS, dispatch_housing_atomic
        self.private_instance()
        now = [time.time()]
        self.service.housing.atomic_saves.clock = lambda: now[0]
        catalog = self.service.housing.catalog
        chosen = [next(item for item in catalog.values() if item["table"] == table)
                  for table in ("HOUSING_CHAIR", "HOUSING_WALLHANGING", "HOUSING_LIGHT")]
        chair, wall, ceiling = [item["item_id"] for item in chosen]
        for item in chosen:
            self.service.housing.grant_item("offline-account-a", item["item_id"], "Local " + item["table"])
        with self.assertRaises(ProtocolError):
            self.service.housing.grant_item("offline-account-a", "invented-id")
        listing = self.call("GetHousingTypeServlet", self.guid, "offline-account-a", "1").split("#")
        self.assertEqual(listing[4:], [chair, "HOUSING_CHAIR", "Local HOUSING_CHAIR"])
        binding = self.service.housing.allocated_binding(self.guid)
        before = self.service.housing.load(binding)

        # A controlled coroutine turn replaces only the wait's timer. The
        # actual async wrapper/Service/submit/ready code runs with sockets still
        # forbidden, and part1 cannot acknowledge before part0 commits.
        class OneTurn:
            def __await__(self):
                yield None
        async def one_turn(_seconds):
            await OneTurn()
        payload1 = encode_entry_fields(self.housing_part([chair] * 101, "1", [wall], [ceiling]), HOUSING_FIELDS)
        message1 = "#".join((self.guid, "offline-account-a", payload1, "1", "StandaloneWindows"))
        with patch("housing_atomic.asyncio.sleep", new=one_turn):
            pending = dispatch_housing_atomic(self.service, "HousingSavePresetServletParts", message1)
            try:
                self.assertIsNone(pending.send(None))
                self.assertEqual(self.service.housing.load(binding), before)
                payload0 = encode_entry_fields(self.housing_part([chair] * 101, "0", [wall], [ceiling]), HOUSING_FIELDS)
                self.assertEqual(self.call("HousingSavePresetServletParts", self.guid, "offline-account-a", payload0, "0").split("#"),
                                 ["true", self.guid, "offline-account-a", "true"])
                with self.assertRaises(StopIteration) as completed:
                    pending.send(None)
                self.assertEqual(completed.exception.value.split("#"), ["true", self.guid, "offline-account-a", "true"])
            finally:
                pending.close()
        fields = self.call("HousingReadPresetServlet", self.guid, "offline-account-a", "Home").split("#")
        saved = json.loads(fields[3])
        self.assertEqual(saved["aidasset"], [chair] * 101)
        self.assertEqual(saved["aidasset_tx"], list(range(1, 102)))
        self.assertEqual(saved["atablename"], ["HOUSING_CHAIR"] * 101 + ["HOUSING_LIGHT", "HOUSING_WALLHANGING"])
        # The original success popup serializes later saves; advance a bounded
        # fixture clock instead of sleeping through its acknowledgement window.
        now[0] += ACK_SECONDS + 0.1
        for part in ("0", "1"):
            payload = encode_entry_fields(self.housing_part([chair], part), HOUSING_FIELDS)
            self.call("HousingSavePresetServletParts", self.guid, "offline-account-a", payload, part)
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.service = Service(self.store, self.catalog)
        saved = json.loads(self.call("HousingReadPresetServlet", self.guid, "offline-account-a", "Home").split("#")[3])
        self.assertEqual(saved["aidasset"], [chair])
        self.assertEqual(saved["atablename"], ["HOUSING_CHAIR"])
        purchases = json.loads(self.call("GetPurchases", self.guid).split("#")[2])
        self.assertEqual(set(purchases["housings"]), {chair, wall, ceiling})
    def test_housing_visitor_read_and_owner_only_write(self):
        self.private_instance()
        other = self.login("offline-account-b", "Other")
        with self.assertRaises(ProtocolError):
            self.call("N2LoadSpace", other, "offline-account-b", "Home", "true", "", "")
        self.presence([(self.guid, 0)])
        self.call("N2LoadSpace", other, "offline-account-b", "Home", "true", "", self.guid)
        fields = self.call("N2HousingReadPreset", other, "offline-account-b", "Home").split("#")
        self.assertEqual(fields[4], self.guid)
        with self.assertRaises(ProtocolError) as error:
            self.call("HousingSavePresetServletParts", other, "offline-account-b", encode_entry_fields(self.housing_part([], "0"), HOUSING_FIELDS), "0")
        self.assertEqual(error.exception.status, 403)

    def test_housing_invite_requires_current_present_owner_not_visitor(self):
        self.private_instance()
        visitor = self.login("offline-account-b", "Visitor")
        self.presence([(self.guid, 0)])
        self.call("N2LoadSpace", visitor, "offline-account-b", "Home", "true", "", self.guid)
        third = self.login("offline-account-c", "Third")
        with self.assertRaises(ProtocolError) as error:
            self.call("N2LoadSpace", third, "offline-account-c", "Home", "true", "", visitor)
        self.assertEqual(error.exception.status, 403)

        # A newer login makes the allocated owner GUID historical.  A stale
        # presence document cannot restore its authority.
        current = self.login("offline-account-a", "Display Name")
        self.presence([(self.guid, 0), (current, 0)])
        with self.assertRaises(ProtocolError) as error:
            self.call("N2LoadSpace", third, "offline-account-c", "Home", "true", "", self.guid)
        self.assertEqual(error.exception.status, 503)

    def test_housing_native_placement_classes_budget_and_scene_slots(self):
        self.private_instance()
        catalog = self.service.housing.catalog
        chair = next(item for item in catalog.values() if item["table"] == "HOUSING_CHAIR")
        wall = next(item for item in catalog.values() if item["table"] == "HOUSING_WALLHANGING")
        ceiling = next(item for item in catalog.values() if item["table"] == "HOUSING_LIGHT")
        for item in (chair, wall, ceiling):
            self.service.housing.grant_item("offline-account-a", item["item_id"])
        # Shipped component identity, rather than manifest naming alone, is the
        # grant boundary. This manifest points at a differently identified prefab.
        self.assertNotIn("X1t8gk182grYH0Hu34WPDHOdt4AORWK7", catalog)
        # Older Assets/ART/ResourcesART paths remain valid when their internal
        # component identity was independently verified.
        self.assertIn("CG22i7HYX1eu6GUgkqYfeLlEvdb4yIts", catalog)
        binding = self.service.housing.allocated_binding(self.guid)
        before = self.service.housing.load(binding)
        for value in (self.housing_part([wall["item_id"]], "0"),
                      self.housing_part([], "0", walls=[chair["item_id"]]),
                      self.housing_part([], "0", ceilings=[chair["item_id"]])):
            counterpart = dict(value)
            counterpart["aidasset"] = ["null"] * len(value["aidasset"])
            for key in ("aidasset_tx", "aidasset_ty", "aidasset_tz", "aidasset_r"):
                counterpart[key] = ["0"] * len(value["aidasset"])
            # Isolate each rejected validation attempt in a test transaction;
            # this does not claim a wire-level recovery from an invalid batch.
            with self.assertRaises(ProtocolError):
                with self.store.atomic():
                    self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                              encode_entry_fields(value, HOUSING_FIELDS), "0")
                    self.assertEqual(self.service.housing.load(binding), before)
                    self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                              encode_entry_fields(counterpart, HOUSING_FIELDS), "1")
            self.assertEqual(self.service.housing.load(binding), before)
        # Home has six wall/ceiling slots; index6 remains rejected at complete
        # layout validation, with matching repeated metadata in both halves.
        with self.assertRaises(ProtocolError):
            with self.store.atomic():
                for part in ("0", "1"):
                    value = self.housing_part([], part, walls=[wall["item_id"]] * 7)
                    self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                              encode_entry_fields(value, HOUSING_FIELDS), part)
        self.assertEqual(self.service.housing.load(binding), before)
        # Both halves of an over-budget201 placement must fail together.
        ids = [chair["item_id"]] * 200
        with self.assertRaises(ProtocolError):
            with self.store.atomic():
                for part in ("0", "1"):
                    value = self.housing_part(ids, part, walls=[wall["item_id"]])
                    self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                              encode_entry_fields(value, HOUSING_FIELDS), part)
        self.assertEqual(self.service.housing.load(binding), before)
        # A separate complete native pair accepts exactly the200-space limit.
        for part in ("0", "1"):
            value = self.housing_part(ids, part)
            self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                      encode_entry_fields(value, HOUSING_FIELDS), part)
        saved = json.loads(self.call("HousingReadPresetServlet", self.guid, "offline-account-a", "Home").split("#")[3])
        self.assertEqual(len(saved["aidasset"]), 200)
        self.assertEqual(saved["aidassetWall"], [])
    def test_housing_native_free_transform_channel_includes_floor_subclass(self):
        # No shipped grant currently uses HousingAssetFloor, so use an explicit
        # synthetic class override to exercise the native combined channel.
        self.private_instance()
        catalog = self.service.housing.catalog
        chair = next(item for item in catalog.values() if item["table"] == "HOUSING_CHAIR")
        self.service.housing.grant_item("offline-account-a", chair["item_id"])
        prior = chair["behaviour"]
        chair["behaviour"] = "floor"
        try:
            value = self.housing_part([chair["item_id"]], "0")
            self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                      encode_entry_fields(value, HOUSING_FIELDS), "0")
            binding = self.service.housing.allocated_binding(self.guid)
            self.assertEqual(self.service.housing.load(binding)["aidasset"], [])
            counterpart = self.housing_part([chair["item_id"]], "1")
            self.call("HousingSavePresetServletParts", self.guid, "offline-account-a",
                      encode_entry_fields(counterpart, HOUSING_FIELDS), "1")
            saved = json.loads(self.call("HousingReadPresetServlet", self.guid, "offline-account-a", "Home").split("#")[3])
            self.assertEqual(saved["aidasset"], [chair["item_id"]])
        finally:
            chair["behaviour"] = prior

    def test_nonmini_module_dispatch_is_integrated(self):
        # 92 non-minigame routes plus the separately owned minigame modules.
        self.assertEqual(len(self.service.ROUTES), 92 + len(self.service.minigames.ROUTES | {"checkRewardGameServlet"})
                         + len(self.service.fullgames.ROUTES))
        self.assertIn("Get_GatherChristmasGetSpacesCompleted", self.service.fullgames.ROUTES)
        self.assertEqual(self.call("GetFeaturesServlet", self.guid, "offline-account-a"),
                         "true#" + self.guid + "#offline-account-a#0")
        self.assertEqual(self.call("checkRewardAvailableServlet", self.guid, "offline-account-a", "Cube"),
                         "true#" + self.guid + "#false")
        self.service.gathering.configure(1, "Local Christmas", active=False, max_items=0)
        self.assertEqual(self.call("Get_GatherStatus", self.guid, "offline-account-a", "1"),
                         "true#" + self.guid + "#offline-account-a#false#1#0")
        self.assertEqual(self.call("checkerToServerDownMaintenanceServlet", self.guid, "offline-account-a"),
                         "true#" + self.guid + "#offline-account-a#0")

    def test_login_alias_multispace_and_wardrobe_lease_capability(self):
        self.descriptor(True)
        self.assertEqual(self.call("N2LoadSpace", self.guid, "offline-account-a", "Login", "true", "", ""), self.guid + "#false#false")
        other = self.login("offline-account-b", "Other")
        self.call("N2LoadSpace", other, "offline-account-b", "Nexus", "false", "", "")
        self.call("SetUserInWardrobe", other, "offline-instance", "1", "MALE", "Other", "", "0", "1", "1", "1", "2", "3", "4")
        self.assertEqual(self.call("Send_CheckIsInWardrobeServlet", self.guid, "offline-account-a", other).split("#")[3], "true")
        snapshot = {"format_version": 1, "generation": time.time(), "instance_id": "offline-instance", "psidglobal": "Nexus", "listening": True,
                    "wardrobe_delivery": "mirror_after_avatar_ready_v1", "avatars": []}
        path = self.path / "instance-avatar-state.json"
        path.write_text(json.dumps(snapshot))
        self.assertEqual(self.call("GetAllInWardrobe", self.guid, "offline-instance"), "OK#")
        snapshot["listening"] = False
        path.write_text(json.dumps(snapshot))
        self.assertIn(other, self.call("GetAllInWardrobe", self.guid, "offline-instance"))
        with self.store.db:
            self.store.db.execute("UPDATE profile_state SET wardrobe_updated_at=? WHERE ps4_id=?", (time.time() - 61, "offline-account-b"))
        self.assertEqual(self.call("Send_CheckIsInWardrobeServlet", self.guid, "offline-account-a", other).split("#")[3], "false")
        self.assertEqual(self.call("GetAllInWardrobe", self.guid, "offline-instance"), "OK#")
        self.call("InWardrobeCheckerServlet", other, "offline-account-b")
        self.assertEqual(self.call("Send_CheckIsInWardrobeServlet", self.guid, "offline-account-a", other).split("#")[3], "true")

    def test_current_session_export_and_matching_durable_poses(self):
        self.descriptor(True)
        self.call("N2LoadSpace", self.guid, "offline-account-a", "Nexus", "false", "", "")
        new_guid = "f" * 32
        self.store.bind_session("offline-account-a", new_guid)
        with self.store.db:
            self.store.db.execute("UPDATE sessions SET created_at=? WHERE guid=?", (time.time() + 0.01, new_guid))
        self.call("N2LoadSpace", new_guid, "offline-account-a", "Nexus", "false", "", "")
        self.call("SetUserInWardrobe", new_guid, "offline-instance", "1", "MALE", "Display Name", "", "0", "1", "1", "1", "2", "3", "4")
        with self.assertRaises(ProtocolError):
            self.call("SetUserInWardrobe", self.guid, "offline-instance", "0", "MALE", "Display Name", "", "0", "1", "1", "1", "9", "9", "9")
        folder = self.path / "instances" / "offline-instance"
        folder.mkdir(parents=True)
        pose = {"format_version": 1, "instance_id": "offline-instance", "psidglobal": "Nexus", "generation": time.time(),
                "poses": [{"ps4_id": "offline-account-a", "position": {"x": 5, "y": 6, "z": 7}, "updated_at": time.time()}]}
        (folder / "instance-poses.json").write_text(json.dumps(pose))
        self.store.export_instance_accounts(self.path)
        accounts = json.loads((self.path / "instance-accounts.json").read_text())["accounts"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["guid"], new_guid)
        self.assertEqual(accounts[0]["allocated_instance_id"], "offline-instance")
        self.assertTrue(accounts[0]["wardrobe_active"])
        self.assertEqual(accounts[0]["position"], {"x": 5, "y": 6, "z": 7})
        self.assertIn("session_created_at", accounts[0])
        remote = self.call("GetPresetGameServlet", new_guid, "offline-account-a", new_guid).split("#")
        self.assertEqual(json.loads(remote[5])["lastPosition_z"], 7)
        pose["psidglobal"] = "AnotherSpace"
        (folder / "instance-poses.json").write_text(json.dumps(pose))
        self.assertEqual(self.store.position("offline-account-a")["position"], {"x": 2, "y": 3, "z": 4})

    def test_consumable_router_keeps_native_envelopes(self):
        self.service.consumables.grant("offline-account-a", "coffee", 1, 3)
        price = self.call("GetConsumablePriceServlet", self.guid, "offline-account-a", "coffee", "0").split("#")
        self.assertEqual(len(price), 9)
        issued = self.call("GetConsumableServlet", self.guid, "offline-account-a", "coffee", "0").split("#")
        self.assertEqual(issued[:6], ["true", self.guid, "offline-account-a", "coffee", "", "true"])
        self.assertEqual(len(issued), 8)


if __name__ == "__main__":
    unittest.main()

