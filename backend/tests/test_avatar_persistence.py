"""Avatar service lifecycle checks using only a temporary local SQLite file.

Appearance values here are synthetic test inputs, not reconstructed game defaults.
No UI, game, backend process, listener, socket or real account is used.
"""
import copy
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(ROOT / "tools"))

from avatar_entry_codec import encode_value_texts
from service import Service
from state import Catalog, Store
from wire import ProtocolError, session_guid


class AvatarPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT / "protocol")
        cls.schemas = json.loads((ROOT / "protocol/bootstrap-response-contracts.json").read_text())
        cls.fields = {gender: next(x for x in cls.schemas["json_and_enum_declarations"] if x["name"] == "JsonClasses.Preset" + gender.title() + "Json")["fields"] for gender in ("MALE", "FEMALE")}
        cls.scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / "work/offline-tests"; cls.scratch.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.block = patch.object(socket, "socket", side_effect=AssertionError("No network in avatar tests")); self.block.start()
        self.temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.file = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.file); self.service = Service(self.store, self.catalog)
        self.account = "offline-avatar-lifecycle"
        self.guid = self.login("a")

    def tearDown(self):
        self.store.close(); self.temp.cleanup(); self.block.stop()

    def call(self, route, *fields):
        return self.service.dispatch(route, "#".join(fields) + "#StandaloneWindows")

    def login(self, nonce):
        self.call("N2UserExist", "Offline Avatar", "v72", "false", self.account, "1.25")
        self.call("ChannelGUIDServlet", self.account, nonce * 64)
        return session_guid(self.account, nonce * 64)

    def reopen_and_login(self):
        self.store.close(); self.store = Store(self.file); self.service = Service(self.store, self.catalog)
        self.guid = self.login("b")

    def serialize(self, preset, gender):
        # Emulate original native582470 ->3c6680, not a canonical admin input.
        # Reader raw39..41 are left scale but writer names them right position;
        # raw42..44 are right position but writer names them left scale.
        native = dict(preset)
        if gender == "FEMALE":
            for axis in "xyz":
                native["f_ch_r_pectoral_jnt_t_" + axis] = preset["f_ch_l_pectoral_jnt_s_" + axis]
                native["f_ch_l_pectoral_jnt_s_" + axis] = preset["f_ch_r_pectoral_jnt_t_" + axis]
        tokens = []
        for field in self.fields[gender]:
            value = native[field["name"]]
            tokens.append(None if value is None else format(value, ".9g") if "float" in field["type_and_modifiers"] else value)
        return encode_value_texts(tokens)

    def save(self, preset, gender, name):
        self.assertEqual(self.call("N2SavePreset", self.guid, self.account, name, "0" if gender == "MALE" else "1", self.serialize(preset, gender)), "true#true")

    def response(self, gender, name=None):
        route = "GetLoadPresetByName" if name else "GetLastUsedPreset"
        fields = [self.guid, self.account, self.guid, "0" if gender == "MALE" else "1"]
        if name: fields.append(name)
        raw = self.call(route, *fields).split("#")
        self.assertEqual(raw[:3], ["true", self.account, gender]); self.assertEqual(len(raw), 6)
        return json.loads(raw[3]), json.loads(raw[4]), json.loads(raw[5])

    def assert_preset_values(self, expected, actual, gender, name):
        self.assertEqual(set(expected), set(actual))
        for field in self.fields[gender]:
            key = field["name"]
            if key == "presetname": self.assertEqual(actual[key], name)
            elif key == "iduser": self.assertEqual(actual[key], self.account)
            elif "float" in field["type_and_modifiers"]:
                self.assertEqual(struct.pack("<f", actual[key]), struct.pack("<f", expected[key]), key)
            else: self.assertEqual(actual[key], expected[key], key)

    def item(self, gender, category, *, exclude=()):
        return next(value for (_, g, c), value in self.catalog.items.items() if g == gender and c == category and value["kind"] == "FBX" and value["item_id"] not in exclude)

    def modified(self, gender):
        preset = copy.deepcopy(self.store.preset(self.account, gender)["preset"])
        preset.update({"b1": 12.5, "b12": 62.5, "b73": 100.0,
                       "skin_color_r": 0.375, "skin_color_g": 0.625, "skin_color_b": 0.875,
                       "itemColor1_r": 0.25, "itemColor1_g": 0.5, "itemColor1_b": 0.75,
                       "hatItem_t_x": 0.125, "hatItem_r_y": 12.5, "hatItem_s_z": 1.125})
        prefix = "" if gender == "MALE" else "f_"
        preset[prefix + "ch_c_head_jnt_s_x"] = 1.03125
        for axis in "xyz":
            preset[("Male" if gender == "MALE" else "Female") + "Root_" + axis] = 0.9375
        return preset

    def test_male_morph_bones_skin_color_and_attachment_survive_fresh_session(self):
        preset = self.modified("MALE"); self.save(preset, "MALE", "MaleMorph")
        self.reopen_and_login()
        actual, assets, position = self.response("MALE")
        self.assert_preset_values(preset, actual, "MALE", "MaleMorph")
        self.assertEqual(position["GUID"], self.guid); self.assertEqual(position["PS4ID"], self.account)
        self.assertTrue(assets["data"])
        # Named-load JSON and game-avatar JSON must carry the same stored values.
        named = self.response("MALE", "MaleMorph")[0]
        game = self.call("GetPresetGameServlet", self.guid, self.account, self.guid).split("#")
        self.assertEqual(json.loads(game[3]), named)

    def test_female_fields_and_gender_selection_survive_fresh_session(self):
        male = self.modified("MALE"); self.save(male, "MALE", "MaleMorph")
        female = self.modified("FEMALE"); female["f_ch_c_stomaf_ch_jnt_s_x"] = 1.0625
        self.save(female, "FEMALE", "FemaleMorph")
        self.reopen_and_login()
        for gender, expected, name in (("MALE", male, "MaleMorph"), ("FEMALE", female, "FemaleMorph")):
            actual = self.response(gender)[0]; self.assert_preset_values(expected, actual, gender, name)
        game = self.call("GetPresetGameServlet", self.guid, self.account, self.guid).split("#")
        self.assertEqual(game[2], "FEMALE"); self.assertEqual(json.loads(game[3])["presetname"], "FemaleMorph")

    def test_female_native_save_named_load_resave_keeps_distinct_pectoral_vectors(self):
        fixture = json.loads((ROOT / "protocol/avatar-female-save-compensation.json").read_text())["synthetic_fixture"]
        preset = self.modified("FEMALE")
        preset.update(fixture["canonical"])
        for name in ("FirstFemaleSave", "SecondFemaleSave"):
            self.save(preset, "FEMALE", name)
            self.reopen_and_login()
            loaded = self.response("FEMALE", name)[0]
            self.assert_preset_values(preset, loaded, "FEMALE", name)
            for key, value in fixture["canonical"].items():
                self.assertEqual(loaded[key], value, key)
            preset = loaded

    def test_canonical_store_input_and_seed_are_not_native_compensated(self):
        seeded = self.store.preset(self.account, "FEMALE")
        self.assertEqual([seeded["preset"]["f_ch_l_pectoral_jnt_s_" + axis] for axis in "xyz"], [1, 1, 1])
        fixture = json.loads((ROOT / "protocol/avatar-female-save-compensation.json").read_text())["synthetic_fixture"]
        canonical = dict(seeded["preset"]); canonical.update(fixture["canonical"])
        canonical["presetname"] = "CanonicalAdmin"
        self.store.save_preset(self.account, "CanonicalAdmin", "FEMALE", canonical, seeded["assets"], seeded["position"])
        loaded = self.response("FEMALE", "CanonicalAdmin")[0]
        self.assertEqual(loaded, canonical)

    def test_two_category_add_then_remove_preserves_other_item_and_ownership(self):
        for gender in ("MALE", "FEMALE"):
            with self.subTest(gender=gender):
                preset = self.modified(gender)
                slot = next(i for i in range(1, 40) if preset["item" + str(i)] == "null")
                hat = self.item(gender, "CLOTH_HEAD_HAT"); hand = self.item(gender, "CLOTH_BODY_HANDITEML")
                for item in (hat, hand): self.store.grant(self.account, item, item_type=2)
                preset["item" + str(slot)] = hat["item_id"]; preset["item" + str(slot + 1)] = hand["item_id"]
                preset["itemColor" + str(slot + 1) + "_r"] = 0.375
                self.save(preset, gender, gender + "Accessories")
                first, assets, _ = self.response(gender)
                parts = assets["data"].split("!"); half = len(parts) // 2; mapping = dict(zip(parts[:half], parts[half:]))
                self.assertEqual(mapping[hat["item_id"]], "CLOTH_HEAD_HAT")
                self.assertEqual(mapping[hand["item_id"]], "CLOTH_BODY_HANDITEML")
                # Native ReadCloth compacts active IDs before padding literal null.
                preset["item" + str(slot)] = hand["item_id"]; preset["item" + str(slot + 1)] = "null"
                for channel in "rgb": preset["itemColor" + str(slot) + "_" + channel] = first["itemColor" + str(slot + 1) + "_" + channel]
                self.save(preset, gender, gender + "Accessories")
                actual, assets, _ = self.response(gender)
                self.assertEqual(actual["item" + str(slot)], hand["item_id"])
                self.assertEqual(actual["itemColor" + str(slot) + "_r"], 0.375)
                self.assertNotIn(hat["item_id"], assets["data"].split("!"))
                self.assertIn(hat["item_id"], {r["item_id"] for r in self.store.inventory(self.account)})

    def test_gender_specific_feet_replacement_has_correct_manifest_category(self):
        for gender in ("MALE", "FEMALE"):
            with self.subTest(gender=gender):
                preset = self.modified(gender); old_id = preset["item3"]
                feet = self.item(gender, "CLOTH_BODY_FEET", exclude=(old_id,))
                self.store.grant(self.account, feet); preset["item3"] = feet["item_id"]
                self.save(preset, gender, gender + "Feet")
                actual, assets, _ = self.response(gender)
                fields = assets["data"].split("!"); count = len(fields) // 2
                self.assertEqual(dict(zip(fields[:count], fields[count:]))[feet["item_id"]], "CLOTH_BODY_FEET")
                self.assertNotIn(old_id, fields[:count]); self.assertEqual(actual["item3"], feet["item_id"])
                # This service preserves caller-supplied high-heel state. It does
                # not infer a new heel value from an uninspected chosen prefab.
                self.assertEqual(actual["highHeel"], preset["highHeel"])

    def test_unowned_or_wrong_gender_item_cannot_replace_current_preset(self):
        before = self.response("MALE")[0]; bad = copy.deepcopy(before)
        wrong = self.item("FEMALE", "CLOTH_HEAD_HAT"); self.store.grant(self.account, wrong)
        bad["item6"] = wrong["item_id"]
        with self.assertRaises(ProtocolError): self.save(bad, "MALE", "Rejected")
        unowned = self.item("MALE", "CLOTH_HEAD_HAT"); bad["item6"] = unowned["item_id"]
        with self.assertRaises(ProtocolError): self.save(bad, "MALE", "Rejected")
        self.assertEqual(self.response("MALE")[0], before)

    def test_maps_only_customization_is_saved_as_its_exact_category(self):
        for gender in ("MALE", "FEMALE"):
            with self.subTest(gender=gender):
                texture = next(value for (_, g, c), value in self.catalog.items.items()
                               if g == gender and c == "CLOTH_BODY_TATTOO" and value["kind"] == "Maps")
                self.store.grant(self.account, texture)
                preset = self.modified(gender)
                slot = next(i for i in range(1, 41) if preset["item" + str(i)] == "null")
                preset["item" + str(slot)] = texture["item_id"]
                self.save(preset, gender, gender + "Tattoo")
                self.reopen_and_login()
                actual, assets, _ = self.response(gender)
                self.assertEqual(actual["item" + str(slot)], texture["item_id"])
                parts = assets["data"].split("!"); half = len(parts) // 2
                self.assertEqual(dict(zip(parts[:half], parts[half:]))[texture["item_id"]], "CLOTH_BODY_TATTOO")

    def test_remote_avatar_uses_target_appearance_but_requester_response_identity(self):
        female = self.modified("FEMALE"); self.save(female, "FEMALE", "RemoteFemale")
        target_account, target_guid = self.account, self.guid
        self.account = "offline-avatar-viewer"; self.guid = self.login("c")
        raw = self.call("GetPresetGameServlet", self.guid, self.account, target_guid).split("#")
        self.assertEqual(raw[:3], ["true", self.account, "FEMALE"])
        actual, position = json.loads(raw[3]), json.loads(raw[5])
        self.assertEqual(actual["iduser"], target_account)
        self.assertEqual(actual["presetname"], "RemoteFemale")
        self.assertEqual(actual["b73"], female["b73"])
        self.assertEqual(position["PS4ID"], target_account); self.assertEqual(position["GUID"], target_guid)


if __name__ == "__main__": unittest.main()

