"""Actual-bundle round-trip and guard tests for preset-name focus."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

import UnityPy


TOOLS = Path(__file__).resolve().parents[1] / "recipes"
sys.path.insert(0, str(TOOLS))
import preset_input_patch as patcher


SOURCE = Path(os.environ["NEBULA_ORIGINAL_CHARACTEREDITOR"]) if os.environ.get("NEBULA_ORIGINAL_CHARACTEREDITOR") else None


class PresetInputPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SOURCE is None or not SOURCE.is_file():
            raise unittest.SkipTest("Reviewed CharacterEditor bundle is unavailable")
        cls.source = SOURCE.read_bytes()
        cls.source_hash = hashlib.sha256(cls.source).hexdigest()
        cls.output, cls.manifest = patcher.prepare(cls.source)

    def test_exact_focus_call_is_appended_after_original_calls(self):
        before = UnityPy.load(self.source)
        after = UnityPy.load(self.output)
        old_tree = patcher._asset_file(before).objects[patcher.BUTTON_PATH_ID].read_typetree()
        new_tree = patcher._asset_file(after).objects[patcher.BUTTON_PATH_ID].read_typetree()
        old_calls = old_tree["m_OnClick"]["m_PersistentCalls"]["m_Calls"]
        new_calls = new_tree["m_OnClick"]["m_PersistentCalls"]["m_Calls"]
        self.assertEqual(new_calls[:2], old_calls)
        self.assertEqual(len(new_calls), 3)
        self.assertEqual(patcher._call_signature(new_calls[2]),
                         (0, patcher.INPUT_PATH_ID, "ActivateInputField", 1, 2))
        self.assertEqual(hashlib.sha256(self.output).hexdigest(), patcher.COPY_SHA256)

    def test_every_other_object_and_streamed_resource_is_identical(self):
        before = UnityPy.load(self.source)
        after = UnityPy.load(self.output)
        exclude = (patcher.ASSET_FILE, patcher.BUTTON_PATH_ID)
        old = patcher._snapshot(before, exclude)
        new = patcher._snapshot(after, exclude)
        self.assertEqual(old, new)
        self.assertEqual(len(old), 41050)
        self.assertTrue(self.manifest[
            "all_other_serialized_objects_and_streamed_resources_preserved"])

    def test_focus_contract_has_active_pc_event_system_and_endedit_save(self):
        env = UnityPy.load(self.output)
        asset = patcher._asset_file(env)
        _, input_tree = patcher._tree(asset, patcher.INPUT_PATH_ID, "MonoBehaviour")
        self.assertNotIn("m_OnEndEdit", input_tree)
        end_call = input_tree["m_OnDidEndEdit"]["m_PersistentCalls"]["m_Calls"][0]
        self.assertEqual(patcher._call_signature(end_call),
                         (0, patcher.SAVE_COMPONENT_PATH_ID, "OnSavePreset", 1, 2))
        _, event_tree = patcher._tree(asset, patcher.PC_SAVE_EVENT_SYSTEM_PATH_ID,
                                      "MonoBehaviour")
        self.assertEqual(event_tree["m_FirstSelected"]["m_PathID"],
                         patcher.INPUT_GAMEOBJECT_PATH_ID)
        _, event_go = patcher._tree(asset, event_tree["m_GameObject"]["m_PathID"],
                                    "GameObject")
        self.assertTrue(event_go["m_IsActive"])

    def test_only_input_type_tree_end_edit_name_is_migrated(self):
        before = UnityPy.load(self.source)
        after = UnityPy.load(self.output)
        old_type = patcher._asset_file(before).objects[patcher.INPUT_PATH_ID].serialized_type
        new_type = patcher._asset_file(after).objects[patcher.INPUT_PATH_ID].serialized_type
        expected = patcher._schema_rows(old_type)
        index = next(i for i, row in enumerate(expected) if row[2] == "m_OnEndEdit")
        expected[index] = (*expected[index][:2], "m_OnDidEndEdit", *expected[index][3:])
        self.assertEqual(patcher._schema_rows(new_type), expected)
        self.assertFalse(self.manifest["changed_type_tree"]["event_payload_bytes_changed"])

    def test_original_is_unchanged_and_unknown_source_fails_closed(self):
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), self.source_hash)
        self.assertEqual(self.source_hash, patcher.ORIGINAL_SHA256)
        damaged = self.source[:-1] + bytes([self.source[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "Source SHA256"):
            patcher.prepare(damaged)

    def test_path_guards_reject_alias_existing_steam_and_bad_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            existing = base / "existing"
            existing.write_bytes(b"x")
            good_manifest = base / "copy.json"
            with self.assertRaisesRegex(ValueError, "Destination"):
                patcher.validate_paths(SOURCE, SOURCE, good_manifest)
            with self.assertRaisesRegex(ValueError, "Destination"):
                patcher.validate_paths(SOURCE, existing, good_manifest)
            with self.assertRaisesRegex(ValueError, "Manifest"):
                patcher.validate_paths(SOURCE, base / "copy", base / "copy.txt")
            steam_copy = Path("EXAMPLE/steamapps/compat-copy/charactereditor")
            with self.assertRaisesRegex(ValueError, "Destination"):
                patcher.validate_paths(SOURCE, steam_copy, good_manifest)


if __name__ == "__main__":
    unittest.main()
