"""Portable TEMP packaging/workflow checks; no patcher/game/bundle execution."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import yaml

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY/'scripts/package_windows_patcher.py'
spec = importlib.util.spec_from_file_location('checked_windows_release_packager', SOURCE)
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)


class Packaging(unittest.TestCase):
    def setUp(self):
        self.no_process = patch('subprocess.Popen', side_effect=AssertionError('No program execution in package tests'))
        self.no_process.start()
        self.temp = tempfile.TemporaryDirectory(prefix='patcher package ')
        self.root = Path(self.temp.name); self.repo = self.root/'source'; (self.repo/'patcher').mkdir(parents=True)
        (self.repo/'patcher/Cargo.toml').write_text('[package]\nname="nebula-preservation-patcher"\nversion="0.1.0"\n')
        (self.repo/'patcher/Cargo.lock').write_bytes(b'version = 4\n')
        (self.repo/'THIRD_PARTY_NOTICES.md').write_bytes(b'Existing dependency notices\n')
        self.binary = self.root/P.EXECUTABLE
        blob = bytearray(512); blob[:2] = b'MZ'; struct.pack_into('<I', blob, 0x3C, 0x80)
        blob[0x80:0x84] = b'PE\0\0'; struct.pack_into('<H', blob, 0x84, 0x8664)
        struct.pack_into('<HHH', blob, 0x80+20, 240, 2, 0x20B)
        self.binary.write_bytes(blob)  # synthetic nonexecuted patcher header only, never a game/bundle
        self.output = self.root/'new-release'

    def tearDown(self):
        self.temp.cleanup(); self.no_process.stop()

    def package(self, **kwargs):
        return P.package(self.repo, self.binary, self.output, **kwargs)

    def test_exact_archive_and_all_checksums_without_invented_license(self):
        result = self.package(commit='a'*40)
        with zipfile.ZipFile(result['archive']) as bundle:
            self.assertEqual(set(bundle.namelist()), {P.EXECUTABLE, 'README.md', 'THIRD_PARTY_NOTICES.md', 'Cargo.lock', 'BUILD-INFO.json', 'SHA256SUMS'})
            info = json.loads(bundle.read('BUILD-INFO.json'))
            self.assertFalse(info['code_signed']); self.assertFalse(info['game_or_patch_bundle_included'])
            self.assertFalse(info['project_license_included']); self.assertEqual(info['source_commit'], 'a'*40)
            for line in bundle.read('SHA256SUMS').decode().splitlines():
                digest, name = line.split('  '); self.assertEqual(digest, hashlib.sha256(bundle.read(name)).hexdigest())
            for item in bundle.infolist():
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0)); self.assertNotIn(str(self.root), bundle.read(item.filename).decode('utf-8', errors='ignore'))
        self.assertEqual((self.output/'SHA256SUMS').read_text(), result['sha256']+'  '+P.ARCHIVE+'\n')

    def test_deterministic_archive_excludes_unselected_extra_private_or_bundle_files(self):
        (self.repo/'publicaccess.conf').write_bytes(b'NEVER INCLUDE')
        (self.repo/'patcher/NebulaAutomation.dll').write_bytes(b'NEVER INCLUDE')
        (self.repo/'patcher/private-bundle.zip').write_bytes(b'NEVER INCLUDE')
        first = self.package(); data = Path(first['archive']).read_bytes()
        self.output = self.root/'second-release'; second = self.package()
        self.assertEqual(data, Path(second['archive']).read_bytes())
        with zipfile.ZipFile(second['archive']) as bundle:
            self.assertNotIn(b'NEVER INCLUDE', b''.join(bundle.read(name) for name in bundle.namelist()))

    def test_selected_license_is_copied_verbatim(self):
        (self.repo/'LICENSE').write_bytes(b'Maintainer selected actual license text\n')
        result = self.package()
        self.assertTrue(result['project_license_included'])
        with zipfile.ZipFile(result['archive']) as bundle:
            self.assertEqual(bundle.read('LICENSE'), (self.repo/'LICENSE').read_bytes())

    def test_ambiguous_project_licenses_are_refused(self):
        (self.repo/'LICENSE').write_bytes(b'one'); (self.repo/'LICENSE.md').write_bytes(b'two')
        with self.assertRaises(ValueError): self.package()
        self.assertFalse(self.output.exists())

    def test_not_pe_wrong_machine_and_invalid_headers_refused_without_output(self):
        original = self.binary.read_bytes()
        cases = [b'not an executable', original[:80]]
        invalid = bytearray(original); struct.pack_into('<H', invalid, 0x84, 0x14C); cases.append(invalid)
        invalid = bytearray(original); struct.pack_into('<I', invalid, 0x3C, 99999); cases.append(invalid)
        invalid = bytearray(original); struct.pack_into('<H', invalid, 0x80+22, 0x2002); cases.append(invalid)
        for raw in cases:
            self.binary.write_bytes(raw)
            with self.assertRaises(ValueError): self.package()
            self.assertFalse(self.output.exists())

    def test_wrong_binary_name_and_injected_commit_refused(self):
        wrong = self.root/'GameAssembly.dll'; wrong.write_bytes(self.binary.read_bytes())
        with self.assertRaises(ValueError): P.package(self.repo, wrong, self.output)
        with self.assertRaises(ValueError): self.package(commit='tag; untrusted shell text')
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir(); (self.output/'original').write_bytes(b'retain')
        with self.assertRaises(ValueError): self.package()
        self.assertEqual((self.output/'original').read_bytes(), b'retain')

    def test_linked_ancestor_is_refused(self):
        original = Path.lstat
        def linked(path):
            info = original(path)
            if path == self.repo/'patcher':
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return info
        with patch.object(Path, 'lstat', linked):
            with self.assertRaises(ValueError): self.package()
        self.assertFalse(self.output.exists())

    def test_unreadable_required_notice_is_not_omitted(self):
        original = Path.open
        def failed(path, *args, **kwargs):
            if path == self.repo/'THIRD_PARTY_NOTICES.md': raise PermissionError('synthetic unreadable notice')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', failed):
            with self.assertRaises(PermissionError): self.package()
        self.assertFalse(self.output.exists())


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPOSITORY/'.github/workflows/patcher.yml').read_text()
        cls.value = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_events_quality_dependency_and_tag_only_write_job(self):
        workflow = self.value
        self.assertEqual(set(workflow['on']), {'push', 'pull_request', 'workflow_call', 'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['jobs']['quality']['uses'], './.github/workflows/quality.yml')
        self.assertEqual(workflow['jobs']['build']['needs'], 'quality')
        release = workflow['jobs']['release']
        self.assertEqual(release['permissions'], {'contents': 'write'})
        self.assertEqual(set(release['needs']), {'quality', 'build'})
        self.assertIn("github.event_name != 'pull_request'", release['if'])
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", release['if'])
        self.assertNotIn('pull_request_target', workflow['on'])

    def test_action_sha_pins_exact_locked_commands_and_no_bundle_step(self):
        expected = {'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
                    'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9',
                    'actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333'}
        uses = {step['uses'] for job in self.value['jobs'].values() for step in job.get('steps', []) if 'uses' in step}
        self.assertEqual(uses, expected)
        build = self.value['jobs']['build']
        self.assertEqual(build['runs-on'], 'windows-2025')
        self.assertEqual(self.value['env']['RUST_TARGET'], 'x86_64-pc-windows-msvc')
        self.assertIn('test --manifest-path patcher/Cargo.toml --locked --target', self.text)
        self.assertIn('build --manifest-path patcher/Cargo.toml --locked --release --target', self.text)
        self.assertIn('fmt --manifest-path patcher/Cargo.toml --all -- --check', self.text)
        self.assertNotIn('build_bundle', self.text); self.assertNotIn('--clobber', self.text)
        checkout = next(step for step in build['steps'] if step.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['persist-credentials'], 'false')
        self.assertNotIn('runner.', str(build.get('env', {})))
        self.assertIn('CARGO_TARGET_DIR=$env:RUNNER_TEMP/patcher-target', build['steps'][0]['run'])
        self.assertIn('CARGO_ENCODED_RUSTFLAGS=', build['steps'][0]['run'])
        self.assertIn('$env:GITHUB_ENV', build['steps'][0]['run'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
