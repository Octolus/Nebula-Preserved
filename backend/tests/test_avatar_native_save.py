"""Native-writer permutation and pinned repair tests; no game or sockets."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
WORKSPACE = ROOT
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(ROOT / "tools"))
from avatar_native_save import normalize_original_native_save
import repair_native_female_presets as repair


class NativeWriterFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((ROOT / "protocol/avatar-female-save-compensation.json").read_text())
        cls.fixture = cls.evidence["synthetic_fixture"]

    def test_source_grounded_native_writer_fixture_is_corrected_without_mutation(self):
        original = self.fixture["native_saved_named_fields"]
        preserved = dict(original)
        actual = normalize_original_native_save(original, "FEMALE")
        self.assertEqual(actual, self.fixture["canonical"])
        self.assertEqual(original, preserved)
        expected = {"f_ch_" + side + "_pectoral_jnt_" + operation + "_" + axis
                    for side, operation in (("r", "t"), ("l", "s")) for axis in "xyz"}
        self.assertEqual({key for key in actual if original[key] != actual[key]}, expected)

    def test_male_named_fields_are_unchanged(self):
        male = {"ch_r_pectoral_jnt_t_x": .125, "ch_l_pectoral_jnt_s_x": 1.25, "MaleRoot_x": .9}
        self.assertEqual(normalize_original_native_save(male, "MALE"), male)

    def test_fixture_uses_current_json_metadata_offsets(self):
        schema = next(row for row in json.loads((ROOT / "protocol/avatar-metadata-schemas.json").read_text())
                      if row["full_name"] == "JsonClasses.PresetFemaleJson")
        by_offset = {int(row["managed_layout_offset"], 16): row["name"] for row in schema["fields"]}
        rows = self.evidence["raw_reader_to_saved_json"]
        self.assertEqual([row["raw_float_index"] for row in rows], list(range(36, 48)))
        for row in rows:
            self.assertEqual(by_offset[int(row["saved_json_object_offset"], 16)], row["native_saved_field"])
        self.assertEqual([row["native_saved_field"] for row in rows[3:9]],
                         ["f_ch_" + side + "_pectoral_jnt_" + operation + "_" + axis
                          for side, operation in (("r", "t"), ("l", "s")) for axis in "xyz"])

    def test_available_native_exports_match_pinned_hashes_and_actual_writer_assignments(self):
        if not (WORKSPACE / "work/evidence/ghidra/functions/3c6680.c").exists():
            self.skipTest("Native work evidence is not distributed with backend")
        for row in self.evidence["sources"]:
            self.assertEqual(hashlib.sha256((WORKSPACE / row["path"]).read_bytes()).hexdigest(), row["sha256"])
        text = (WORKSPACE / "work/evidence/ghidra/functions/3c6680.c").read_text()
        text = text[text.index("uVar10 = ManagerPreset__ReadFemaleBonesNETGCloud"):]
        pattern = r"uVar12 = .*?\(lVar6,(0x[0-9a-f]+|[0-9]+),.*?\);\s*\*\(undefined4 \*\)\(lVar3 \+ (0x[0-9a-f]+|[0-9]+)\) = uVar12;"
        actual = {int(index, 0): int(offset, 0) for index, offset in re.findall(pattern, text, re.S)}
        for row in self.evidence["raw_reader_to_saved_json"]:
            self.assertEqual(actual[row["raw_float_index"]], int(row["saved_json_object_offset"], 16))


class ReviewedRepair(unittest.TestCase):
    def setUp(self):
        self.block = patch.object(socket, "socket", side_effect=AssertionError("No network in repair tests")); self.block.start()
        scratch = Path(tempfile.gettempdir()) / "nebula-preserved-tests/native-save"; scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.file = Path(self.temp.name) / "state.sqlite3"
        self.account = "12345678901234567"
        self.raw = json.dumps({**{key: index + .125 for index, key in enumerate(repair.FIELDS)}, "unchanged": 42}, separators=(",", ":"))
        self.pins = {name: repair.digest(self.raw) for name in ("SyntheticMorph", "SyntheticOutfit")}
        self.patch_account = patch.object(repair, "ACCOUNT_SHA256", repair.digest(self.account)); self.patch_account.start()
        self.patch_pins = patch.object(repair, "PINNED_BEFORE", self.pins); self.patch_pins.start()
        with closing(sqlite3.connect(self.file)) as connection, connection:
            connection.executescript("CREATE TABLE profiles(ps4_id TEXT,platform TEXT); CREATE TABLE presets(ps4_id TEXT,name TEXT,gender TEXT,preset_json TEXT,assets_json TEXT,position_json TEXT,updated_at REAL); CREATE TABLE preset_selection(ps4_id TEXT,gender TEXT,name TEXT);")
            connection.execute("INSERT INTO profiles VALUES(?,?)", (self.account, "StandaloneWindows"))
            for name in (*self.pins, "Default"):
                connection.execute("INSERT INTO presets VALUES(?,?,?,?,?,?,?)", (self.account, name, "FEMALE", self.raw, '{"data":"original"}', '{"y":13.3}', 123.0))
            connection.execute("INSERT INTO preset_selection VALUES(?,?,?)", (self.account, "FEMALE", "SyntheticOutfit"))

    def tearDown(self):
        self.patch_pins.stop(); self.patch_account.stop(); self.temp.cleanup(); self.block.stop()

    def plan(self):
        connection = repair.readonly(self.file)
        try: return repair.prepare(connection)
        finally: connection.close()

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.file)) as connection:
            return {table: list(connection.execute("SELECT * FROM " + table)) for table in ("profiles", "presets", "preset_selection")}

    def test_preparation_is_read_only_and_does_not_expose_identity(self):
        before = self.snapshot(); plan = self.plan()
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn(self.account, json.dumps(plan))
        self.assertEqual({row["name"] for row in plan["changes"]}, set(self.pins))

    def test_explicit_reviewed_apply_backs_up_and_changes_only_six_fields_once(self):
        before = self.snapshot(); plan = self.plan(); backup = Path(self.temp.name) / "backup.sqlite3"
        repair.apply_reviewed(self.file, plan, repair.digest(repair.canonical(plan)), backup)
        self.assertEqual(self.snapshot(backup), before)
        after = self.snapshot()
        self.assertEqual(after["profiles"], before["profiles"])
        self.assertEqual(after["preset_selection"], before["preset_selection"])
        for old, new in zip(before["presets"], after["presets"]):
            self.assertEqual(old[:3], new[:3]); self.assertEqual(old[4:], new[4:])
            if old[1] == "Default": self.assertEqual(old, new)
            else:
                a, b = json.loads(old[3]), json.loads(new[3])
                self.assertEqual({key for key in a if a[key] != b[key]}, set(repair.FIELDS))
                self.assertEqual(a["unchanged"], b["unchanged"])
        with self.assertRaises(ValueError): self.plan()

    def test_changed_row_or_wrong_plan_hash_refuses_before_backup_or_write(self):
        plan = self.plan(); backup = Path(self.temp.name) / "backup.sqlite3"
        with self.assertRaises(ValueError): repair.apply_reviewed(self.file, plan, "0" * 64, backup)
        self.assertFalse(backup.exists())
        with closing(sqlite3.connect(self.file)) as connection, connection:
            connection.execute("UPDATE presets SET preset_json='{}' WHERE name='SyntheticOutfit'")
        before = self.snapshot()
        with self.assertRaises(ValueError): repair.apply_reviewed(self.file, plan, repair.digest(repair.canonical(plan)), backup)
        self.assertFalse(backup.exists()); self.assertEqual(self.snapshot(), before)


if __name__ == "__main__": unittest.main()



