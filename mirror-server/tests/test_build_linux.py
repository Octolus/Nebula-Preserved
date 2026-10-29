"""Offline build-result checks; Unity and scene servers are never invoked."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).absolute().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load("portable_linux_builder", HERE.parent / "build_linux.py")
REPOSITORY = Path(__file__).absolute().parents[2]
supervisor = load("existing_instance_supervisor", REPOSITORY / "tools/instance_supervisor.py")


def elf_header():
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    return bytes(header)


class LinuxBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nebula Linux build fixture ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source with spaces" / "mirror-server"
        self.root.mkdir(parents=True)
        # Copy the actual currently selected sources into a new temporary tree.
        for relative in builder.SOURCE_PATHS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPOSITORY / "mirror-server" / relative).read_bytes())
        self.version = self.root / "UnityProject/ProjectSettings/ProjectVersion.txt"
        self.version.parent.mkdir(parents=True)
        self.version.write_text("m_EditorVersion: 6000.6.3f1\n", encoding="utf-8")
        self.unity = self.base / "editor with spaces" / "Unity"
        self.unity.parent.mkdir()
        self.unity.write_bytes(b"Not executed; offline fixture only")
        self.unity.chmod(0o755)
        self.output = self.root / "build-linux"
        self.report = self.root / "build-linux-validation.json"
        self.calls = []

    def output_fixture(self):
        self.output.mkdir(exist_ok=True)
        executable = self.output / "NebulaServer.x86_64"
        executable.write_bytes(elf_header() + b"synthetic player")
        executable.chmod(0o755)
        managed = self.output / "NebulaServer_Data/Managed/Assembly-CSharp.dll"
        managed.parent.mkdir(parents=True, exist_ok=True)
        managed.write_bytes(b"synthetic managed assembly")
        for number in range(149):
            asset = self.output / "NebulaServer_Data/fixture" / f"artifact-{number:03d}.bin"
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(f"synthetic build artifact {number}".encode())

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        self.output_fixture()
        Path(command[-1]).write_text(builder.MARKER + "\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    def build(self, run=None):
        return builder.build(self.root, self.unity, run=run or self.runner)

    def config(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        return supervisor.Config(
            state_dir=self.base / "unused-state", binary=self.output / "NebulaServer.x86_64",
            build_report=self.report, build_report_sha256=builder.sha256(self.report),
            binary_sha256=report["executable_sha256"],
            managed_assembly_sha256=report["managed_assembly_sha256"],
            bind="127.0.0.1", advertise_ip="127.0.0.1", first_port=28000,
            last_port=28001, max_processes=1, max_records=2,
            allowed_scenes=frozenset({"Nexus"}), allowed_profiles=frozenset({"nonmini-semantic-v1"}))

    def assert_failure_preserves(self, runner, message):
        self.report.write_bytes(b"previous report stays byte identical\n")
        before = self.report.read_bytes()
        with self.assertRaisesRegex(builder.BuildError, message):
            self.build(runner)
        self.assertEqual(self.report.read_bytes(), before)
        self.assertFalse((self.root / ".build-linux.lock").exists())
        self.assertEqual(list(self.root.glob(".build-linux-validation-*.tmp")), [])

    def test_complete_151_report_passes_actual_supervisor_validator(self):
        report = self.build()
        self.assertEqual(len(report["source_hashes"]), 21)
        self.assertEqual(len(report["artifacts"]), 151)
        self.assertEqual(supervisor.validate_build(self.config()), report["executable_sha256"])
        for row in report["source_hashes"]:
            self.assertEqual(builder.sha256(self.root / row["path"]), row["sha256"])
        for row in report["artifacts"]:
            self.assertEqual(builder.sha256(self.output / row["path"]), row["sha256"])
            self.assertEqual((self.output / row["path"]).stat().st_size, row["size"])
        text = self.report.read_text(encoding="utf-8")
        self.assertNotIn(str(self.unity), text)
        self.assertNotIn(str(self.root), text)
        self.assertEqual([report[key] for key in ("game_launched", "reconstructed_listener_started",
                                                "linux_runtime_tested", "networking_parity_proven")], [False] * 4)

    def test_subprocess_arguments_are_unquoted_distinct_arguments(self):
        self.build()
        command, options = self.calls[0]
        self.assertEqual(command, [str(self.unity), "-batchmode", "-nographics", "-quit",
            "-projectPath", str(self.root / "UnityProject"), "-buildTarget", "Linux64",
            "-standaloneBuildSubtarget", "Server", "-executeMethod",
            "PreservationBuild.BuildLinuxServer", "-logFile", command[-1]])
        self.assertEqual(options["cwd"], str(self.root / "UnityProject"))
        self.assertNotIn("shell", options)
        self.assertFalse(options["check"])

    def test_existing_artifacts_preserved_and_inventoried(self):
        self.output.mkdir()
        extra = self.output / "existing-operator-file.bin"
        extra.write_bytes(b"do not delete")
        report = self.build()
        self.assertEqual(extra.read_bytes(), b"do not delete")
        self.assertEqual(len(report["artifacts"]), 152)
        self.assertIn("existing-operator-file.bin", {row["path"] for row in report["artifacts"]})

    def test_failed_unity_even_with_marker_never_replaces_report(self):
        def run(*args, **kwargs):
            self.runner(*args, **kwargs)
            return SimpleNamespace(returncode=9)
        self.assert_failure_preserves(run, "exit code 9")

    def test_missing_marker_does_not_reuse_old_log(self):
        (self.root / "build-linux.log").write_text(builder.MARKER, encoding="utf-8")
        def run(command, **kwargs):
            self.runner(command, **kwargs)
            Path(command[-1]).write_text("Unity did not report success", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        self.assert_failure_preserves(run, "without.*marker")

    def test_source_changed_during_build(self):
        def run(*args, **kwargs):
            result = self.runner(*args, **kwargs)
            source = self.root / builder.SOURCE_PATHS[0]
            source.write_bytes(source.read_bytes() + b"\n// changed\n")
            return result
        self.assert_failure_preserves(run, "Sources changed")

    def test_source_added_during_build(self):
        def run(*args, **kwargs):
            result = self.runner(*args, **kwargs)
            (self.root / "UnityProject/Assets/Preservation/Unexpected.cs").write_text("// extra", encoding="utf-8")
            return result
        self.assert_failure_preserves(run, "reviewed set")

    def test_missing_source_rejected_before_editor(self):
        (self.root / builder.SOURCE_PATHS[0]).unlink()
        with self.assertRaises(builder.BuildError):
            self.build()
        self.assertEqual(self.calls, [])

    def test_unreadable_artifact_subtree_preserves_previous_report(self):
        real_scandir = os.scandir
        denied = self.output / "NebulaServer_Data/fixture"
        def scandir(path):
            if Path(path) == denied:
                raise PermissionError("offline unreadable artifact subtree")
            return real_scandir(path)
        with patch.object(builder.os, "scandir", side_effect=scandir):
            self.assert_failure_preserves(self.runner, "Cannot enumerate the complete")
        self.assertEqual(len([p for p in self.output.rglob("*") if p.is_file()]), 151)
        self.assertEqual(len(self.calls), 1)

    def test_hidden_extra_source_subtree_denied_before_editor(self):
        hidden = self.root / "UnityProject/Assets/Preservation/unreadable"
        hidden.mkdir()
        extra = hidden / "Unexpected.cs"
        extra.write_text("// extra C# source must never be hidden by a scan error\n", encoding="utf-8")
        self.report.write_bytes(b"previous accepted report\n")
        previous = self.report.read_bytes()
        real_scandir = os.scandir
        def scandir(path):
            if Path(path) == hidden:
                raise PermissionError("offline unreadable source subtree")
            return real_scandir(path)
        with patch.object(builder.os, "scandir", side_effect=scandir):
            with self.assertRaisesRegex(builder.BuildError, "Cannot enumerate the complete"):
                self.build()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.report.read_bytes(), previous)
        self.assertFalse((self.root / ".build-linux.lock").exists())
        self.assertTrue(extra.is_file())
        with self.assertRaisesRegex(builder.BuildError, "reviewed set"):
            builder.source_hashes(self.root)

    def test_wrong_project_editor_version_rejected_before_editor(self):
        self.version.write_text("m_EditorVersion: 2020.3.0f1\n", encoding="utf-8")
        with self.assertRaisesRegex(builder.BuildError, "project version"):
            self.build()
        self.assertEqual(self.calls, [])

    def test_missing_or_directory_editor_rejected(self):
        for editor in (self.base / "missing", self.base):
            with self.subTest(editor=editor), self.assertRaises(builder.BuildError):
                builder.build(self.root, editor, run=self.runner)
        self.assertEqual(self.calls, [])

    def test_malformed_elf_variants_preserve_report(self):
        variants = {"truncated": elf_header()[:20], "PE": b"MZ" + b"\0" * 62}
        for label, position, value in (("32bit", 4, 1), ("big-endian", 5, 2),
                                       ("machine-arm", 18, 183), ("header-size", 52, 52),
                                       ("relocatable", 16, 1), ("bad-version", 20, 0)):
            header = bytearray(elf_header())
            header[position] = value
            variants[label] = bytes(header)
        for label, content in variants.items():
            def run(*args, **kwargs):
                result = self.runner(*args, **kwargs)
                (self.output / "NebulaServer.x86_64").write_bytes(content)
                return result
            with self.subTest(label=label):
                self.assert_failure_preserves(run, "ELF64")

    def test_missing_managed_assembly_preserves_report(self):
        def run(*args, **kwargs):
            result = self.runner(*args, **kwargs)
            (self.output / "NebulaServer_Data/Managed/Assembly-CSharp.dll").unlink()
            return result
        self.assert_failure_preserves(run, "missing")

    def test_existing_build_lock_refuses_editor(self):
        (self.root / ".build-linux.lock").write_text("other build", encoding="utf-8")
        with self.assertRaisesRegex(builder.BuildError, "Another build"):
            self.build()
        self.assertEqual(self.calls, [])
        self.assertEqual((self.root / ".build-linux.lock").read_text(), "other build")

    def test_output_path_must_be_directory(self):
        self.output.write_bytes(b"not a directory")
        with self.assertRaisesRegex(builder.BuildError, "wrong file type"):
            self.build()
        self.assertEqual(self.calls, [])

    def link(self, path, target, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"Host cannot create symbolic links: {exc}")

    def test_source_symlink_rejected_before_editor(self):
        source = self.root / builder.SOURCE_PATHS[0]
        outside = self.base / "external-source.cs"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        self.link(source, outside)
        with self.assertRaisesRegex(builder.BuildError, "Linked"):
            self.build()
        self.assertEqual(self.calls, [])

    def test_output_directory_symlink_rejected_before_editor(self):
        outside = self.base / "external-output"
        outside.mkdir()
        self.link(self.output, outside, directory=True)
        with self.assertRaisesRegex(builder.BuildError, "Linked"):
            self.build()
        self.assertEqual(self.calls, [])

    def test_output_file_symlink_added_by_build_rejected(self):
        def run(*args, **kwargs):
            result = self.runner(*args, **kwargs)
            self.link(self.output / "linked-artifact.bin", self.unity)
            return result
        self.assert_failure_preserves(run, "Linked")

    def test_report_symlink_never_overwrites_target(self):
        outside = self.base / "external-report"
        outside.write_bytes(b"outside stays intact")
        self.link(self.report, outside)
        with self.assertRaisesRegex(builder.BuildError, "Linked"):
            self.build()
        self.assertEqual(self.calls, [])
        self.assertEqual(outside.read_bytes(), b"outside stays intact")

    def test_linked_editor_rejected_before_invocation(self):
        linked = self.base / "Unity-link"
        self.link(linked, self.unity)
        with self.assertRaisesRegex(builder.BuildError, "Linked"):
            builder.build(self.root, linked, run=self.runner)
        self.assertEqual(self.calls, [])

    def test_supervisor_refuses_later_artifact_tamper(self):
        self.build()
        config = self.config()
        config.binary.write_bytes(config.binary.read_bytes() + b"tampered")
        with self.assertRaisesRegex(supervisor.ContractError, "binary SHA"):
            supervisor.validate_build(config)

    def test_explicit_build_flag_required_and_import_has_no_execution(self):
        with patch.object(builder, "build", side_effect=AssertionError("must not invoke")):
            with self.assertRaises(SystemExit) as exit_info:
                builder.main(["--unity", str(self.unity)])
        self.assertEqual(exit_info.exception.code, 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
