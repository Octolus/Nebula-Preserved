"""Offline tests for the exact-build F8/L3 keyboard compatibility copy."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pefile


ROOT = workspace()
TOOL = Path(__file__).with_name("keyboard_focus_patch.py")
BASELINE = ROOT / "work/patched-client-keyboard-buttons/GameAssembly.dll"
ORIGINAL = ROOT / "work/evidence/GameAssembly.dll"
# Bind preparation tests to the immutable reviewed input, not the active client
# which can legitimately receive later compatible input additions.
INPUT = ROOT / "work/patched-input-world/globalgamemanagers"
SPEC = importlib.util.spec_from_file_location("keyboard_focus_patch", TOOL)
patch = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(patch)


class KeyboardFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BASELINE.read_bytes()
        cls.output, cls.manifest = patch.build(cls.source, ORIGINAL.read_bytes(), INPUT.read_bytes())

    def test_deterministic_reviewed_hashes(self):
        again, manifest = patch.build(self.source, ORIGINAL.read_bytes(), INPUT.read_bytes())
        self.assertEqual(again, self.output)
        self.assertEqual(manifest["copy_sha256"], "ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b")

    def test_only_l3_immediate_and_checksum_change(self):
        pe = pefile.PE(data=self.source, fast_load=True)
        l3 = pe.get_offset_from_rva(patch.L3_STUB_RVA)
        checksum = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
        changed = {i for i, (a, b) in enumerate(zip(self.source, self.output)) if a != b}
        self.assertEqual(changed - set(range(checksum, checksum + 4)), {l3 + 2})
        self.assertEqual(self.source[l3:l3 + 6], patch.OLD_INSTRUCTION)
        self.assertEqual(self.output[l3:l3 + 6], patch.NEW_INSTRUCTION)

    def test_redirects_keycodes_exception_and_sections_preserved(self):
        before = patch._pe(self.source, exceptions=True)
        after = patch._pe(self.output, exceptions=True)
        self.assertEqual(patch._redirects(self.source, before), patch._redirects(self.output, after))
        expected = patch._stub_keycodes(self.source, before); expected["L3"] = 289
        self.assertEqual(patch._stub_keycodes(self.output, after), expected)
        self.assertEqual(patch._runtime_rows(before), patch._runtime_rows(after))
        self.assertEqual([bytes(s.__pack__()) for s in before.sections],
                         [bytes(s.__pack__()) for s in after.sections])
        directory = before.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        start = before.get_offset_from_rva(directory.VirtualAddress)
        self.assertEqual(self.source[start:start + directory.Size], self.output[start:start + directory.Size])

    def test_f8_bounded_reservation_evidence(self):
        evidence = self.manifest["bounded_f8_reservation_evidence"]
        self.assertEqual(evidence["recovered_immediates"], [273, 274])
        self.assertFalse(evidence["f8_immediate_289_found"])
        self.assertEqual(evidence["input_manager_axis_count"], 48)
        self.assertEqual(evidence["serialized_f8_bindings"], [])

    def test_controller_first_policy_model(self):
        def model(original, blocked, reset, down, held):
            if original:
                return True
            if blocked:
                return False
            return down if reset else held
        cases = [
            ((True, False, True, False, False), True),
            ((True, True, False, False, False), True),
            ((False, True, True, True, True), False),
            ((False, False, True, True, False), True),
            ((False, False, True, False, True), False),
            ((False, False, False, False, True), True),
            ((False, False, False, True, False), False),
        ]
        for args, expected in cases:
            with self.subTest(args=args): self.assertEqual(model(*args), expected)

    def test_hash_guard_rejects_modified_source(self):
        bad = bytearray(self.source); bad[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            patch.build(bytes(bad), ORIGINAL.read_bytes(), INPUT.read_bytes())

    def test_cli_refuses_existing_destination_and_alias(self):
        common = [sys.executable, str(TOOL), "--source", str(BASELINE), "--original-native", str(ORIGINAL),
                  "--input-manager", str(INPUT)]
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
            folder = Path(folder); existing = folder / "existing.dll"; existing.write_bytes(b"x")
            result = subprocess.run(common + ["--destination", str(existing),
                                    "--manifest", str(folder / "unused.json")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0); self.assertIn("new distinct path", result.stderr)
            result = subprocess.run(common + ["--destination", str(BASELINE),
                                    "--manifest", str(folder / "unused2.json")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0); self.assertIn("new distinct path", result.stderr)

    def test_cli_refuses_steam_destination(self):
        # The guard executes before any parent-directory creation, so this path is never written.
        fake = ROOT / "work/steamapps/keyboard-focus-never-created.dll"
        result = subprocess.run([sys.executable, str(TOOL), "--source", str(BASELINE),
            "--original-native", str(ORIGINAL), "--input-manager", str(INPUT),
            "--destination", str(fake), "--manifest", str(ROOT / "work/never-created.json")],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0); self.assertIn("outside steamapps", result.stderr)
        self.assertFalse(fake.exists())


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(KeyboardFocusTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "format_version": 1, "kind": "keyboard_focus_f8_offline_test_report",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "passed": result.wasSuccessful(), "candidate_sha256": KeyboardFocusTests.manifest["copy_sha256"],
        "target_executed": False, "network_used": False,
    }
    print("REPORT " + json.dumps(report, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
