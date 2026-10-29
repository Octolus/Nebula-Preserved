"""Round-trip and guard tests for the keyboard InputManager copy."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

import UnityPy


TOOLS = Path(__file__).resolve().parents[1] / "recipes"
sys.path.insert(0, str(TOOLS))
import keyboard_input_patch as patcher


SOURCE = Path(os.environ["NEBULA_ORIGINAL_GLOBALGAMEMANAGERS"]) if os.environ.get("NEBULA_ORIGINAL_GLOBALGAMEMANAGERS") else None


class KeyboardInputPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SOURCE is None or not SOURCE.is_file():
            raise unittest.SkipTest("Reviewed Nebula Realms globalgamemanagers is unavailable")
        cls.source = SOURCE.read_bytes()
        cls.source_hash = hashlib.sha256(cls.source).hexdigest()
        cls.output, cls.manifest = patcher.prepare(cls.source)

    def test_actual_asset_roundtrip_has_only_requested_axis_changes(self):
        before = UnityPy.load(self.source)
        after = UnityPy.load(self.output)
        before_manager = patcher._one_input_manager(before)
        after_manager = patcher._one_input_manager(after)
        old_axes = before_manager.read_typetree()["m_Axes"]
        new_axes = after_manager.read_typetree()["m_Axes"]
        expected = copy.deepcopy(old_axes)
        submit_number, submit = patcher._one_named_axis(expected, "Submit")
        expected[submit_number]["positiveButton"] = "return"
        expected.extend([
            patcher._keyboard_axis(submit, "dpad1_horizontal", "left", "right"),
            patcher._keyboard_axis(submit, "dpad1_vertical", "down", "up"),
        ])
        self.assertEqual(new_axes, expected)
        self.assertEqual(new_axes[submit_number]["altPositiveButton"], "joystick 1 button 0")
        self.assertEqual(after.file.unity_version, before.file.unity_version)
        self.assertEqual(hashlib.sha256(self.output).hexdigest(), patcher.DEFAULT_COPY_SHA256)

    def test_optional_world_controls_append_exact_wasd_and_ijkl_rows(self):
        output, manifest = patcher.prepare(self.source, world_controls=True)
        before = UnityPy.load(self.source)
        after = UnityPy.load(output)
        before_manager = patcher._one_input_manager(before)
        after_manager = patcher._one_input_manager(after)
        old_axes = before_manager.read_typetree()["m_Axes"]
        new_axes = after_manager.read_typetree()["m_Axes"]
        self.assertEqual(len(new_axes), len(old_axes) + 6)
        self.assertEqual(
            [(a["m_Name"], a["negativeButton"], a["positiveButton"])
             for a in new_axes[-4:]],
            [("leftstick1horizontal", "a", "d"),
             ("leftstick1vertical", "w", "s"),
             ("rightstick1horizontal", "j", "l"),
             ("rightstick1vertical", "i", "k")],
        )
        for axis in new_axes[-4:]:
            self.assertEqual((axis["type"], axis["gravity"], axis["sensitivity"], axis["joyNum"]),
                             (0, 1000.0, 1000.0, 0))
            self.assertAlmostEqual(axis["dead"], 0.001)
        self.assertEqual(patcher._object_hashes(before, before_manager.path_id),
                         patcher._object_hashes(after, after_manager.path_id))
        self.assertTrue(manifest["world_controls"])
        self.assertEqual(manifest["mode"], "menu_and_world_keyboard")

    def test_all_other_serialized_object_bytes_are_identical(self):
        before = UnityPy.load(self.source)
        after = UnityPy.load(self.output)
        before_manager = patcher._one_input_manager(before)
        after_manager = patcher._one_input_manager(after)
        self.assertEqual(patcher._object_hashes(before, before_manager.path_id),
                         patcher._object_hashes(after, after_manager.path_id))
        self.assertTrue(self.manifest["all_non_input_manager_object_raw_hashes_preserved"])

    def test_original_is_unchanged_and_wrong_build_fails_closed(self):
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
            with self.assertRaisesRegex(ValueError, "Manifest"):
                patcher.validate_paths(SOURCE, base / "copy", base / "copy")
            steam_destination = Path("EXAMPLE/steamapps/compat-copy/globalgamemanagers")
            with self.assertRaisesRegex(ValueError, "Destination"):
                patcher.validate_paths(SOURCE, steam_destination, good_manifest)


if __name__ == "__main__":
    unittest.main()
