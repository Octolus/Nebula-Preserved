"""TEMP fake compiled artifacts/Unity receipts only; no editor or runtime launch."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import ci_linux_runtime as ci

REPO = Path(__file__).resolve().parents[1]
class Collector(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.repo = Path(self.temp.name)
        self.root, self.before, self.receipt, self.dest = ci.paths(self.repo)
        builder = ci.helper(REPO)
        for name in ('build_linux.py', ci.WRAPPER, *builder.SOURCE_PATHS):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / 'mirror-server' / name, path)
    def ready(self):
        self.preparation = ci.prepare(self.repo)['preparation_sha256']; prep = json.loads(self.before.read_text())
        self.proof = dict(format_version=1, nonce=prep['nonce'], preparation_sha256=self.preparation,
            unity_editor=prep['unity_editor'], source_hashes_before=prep['source_hashes'], source_hashes_after=prep['source_hashes'],
            wrapper_sha256=prep['wrapper_sha256'], success_marker=ci.helper(self.repo).MARKER,
            marker_observed=True, original_returned=True)
        self.receipt.write_text(json.dumps(self.proof))
        header = bytearray(64); header[:7] = b'\x7fELF\x02\x01\x01'
        for offset, size, value in ((16,2,2), (18,2,62), (20,4,1), (52,2,64)): header[offset:offset+size] = value.to_bytes(size,'little')
        for name, data in {'NebulaServer.x86_64': header, 'NebulaServer_Data/Managed/Assembly-CSharp.dll': b'fake managed artifact',
                           'NebulaServer_Data/Plugins/test.so': b'fake native artifact', 'UnityPlayer.so': b'fake engine artifact'}.items():
            path = self.root / 'build-linux' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        (self.root / 'build-linux/NebulaServer.x86_64').chmod(0o755)
    def run_collect(self): return ci.collect(self.repo, self.preparation)
    def test_full_tree_canonical_report_and_exact_three_environment_pins(self):
        self.ready(); values = self.run_collect(); report = json.loads((self.dest / 'build-linux-validation.json').read_text())
        tree = ast.parse((self.root / 'build_linux.py').read_text())
        original = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value,ast.Dict) and any(isinstance(t,ast.Name) and t.id=='report' for t in n.targets))
        self.assertEqual(set(report), {key.value for key in original.keys}); self.assertEqual(len(report['source_hashes']), 21)
        self.assertEqual(len(report['artifacts']), 4); self.assertFalse(report['linux_runtime_tested']); self.assertFalse(report['game_launched'])
        self.assertEqual(ci.artifacts(ci.helper(self.repo), self.dest/'build'), report['artifacts'])
        env = dict(line.split('=',1) for line in (self.dest/'runtime.env').read_text().splitlines())
        self.assertEqual(env, dict(NEBULA_BUILD_REPORT_SHA256=values['report_sha256'], NEBULA_SERVER_SHA256=values['server_sha256'], NEBULA_MANAGED_SHA256=values['managed_sha256']))
        with self.assertRaises(ValueError): self.run_collect()
    def test_missing_marker_nonreturn_or_wrong_editor_cannot_collect(self):
        self.ready()
        for key, value in [('marker_observed',False), ('original_returned',False), ('unity_editor','wrong'), ('success_marker','forged'), ('nonce','0'*32)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.receipt.write_text(json.dumps(dict(self.proof, **{key:value}))); self.run_collect()
        self.receipt.unlink()
        with self.assertRaises(ValueError): self.run_collect()
    def test_prepare_refuses_every_stale_output_before_writing(self):
        for name in ('ci-source-before.json','ci-build-receipt.json','build-linux','build-linux-validation.json','.build-linux.lock'):
            path = self.root/name; path.write_text('stale')
            with self.subTest(name=name), self.assertRaises(ValueError): ci.prepare(self.repo)
            path.unlink()
        self.dest.mkdir(parents=True)
        with self.assertRaises(ValueError): ci.prepare(self.repo)
    def test_preparation_tamper_wrong_sha_and_each_source_boundary(self):
        self.ready()
        with self.assertRaises(ValueError): ci.collect(self.repo, '0'*64)
        for relative in (ci.helper(self.repo).SOURCE_PATHS[0], ci.WRAPPER, 'build_linux.py'):
            path = self.root/relative; original = path.read_bytes(); path.write_bytes(original+b'\n')
            with self.subTest(path=relative), self.assertRaises(ValueError): self.run_collect()
            path.write_bytes(original)
        self.before.write_text(self.before.read_text()+' ')
        with self.assertRaises(ValueError): self.run_collect()
    def test_wrong_elf_refused_without_publishing(self):
        self.ready(); (self.root/'build-linux/NebulaServer.x86_64').write_bytes(b'MZ'+b'\0'*62)
        with self.assertRaises(ValueError): self.run_collect()
        self.assertFalse(self.dest.exists()); self.assertFalse((self.root/'build-linux-validation.json').exists())
    def test_copied_artifact_tamper_refused_and_partial_output_never_overwritten(self):
        self.ready(); copy = shutil.copytree
        def corrupt(*args, **kwargs):
            result = copy(*args, **kwargs); (Path(args[1])/'UnityPlayer.so').write_bytes(b'tampered'); return result
        with patch.object(ci.shutil, 'copytree', side_effect=corrupt), self.assertRaises(ValueError): self.run_collect()
        self.assertFalse((self.dest/'runtime.env').exists())
        with self.assertRaises(ValueError): self.run_collect()
    def test_cli_github_output_keys_are_only_reviewed_hashes(self):
        output = self.repo/'github-output'
        with patch.object(ci, '__file__', str(self.repo/'scripts/ci_linux_runtime.py')), patch.dict(os.environ,GITHUB_OUTPUT=str(output)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ci.main(['prepare']),0)
        self.assertEqual(set(dict(line.split('=',1) for line in output.read_text().splitlines())), {'preparation_sha256'})
    def test_collect_cli_github_output_contract(self):
        self.ready(); output = self.repo/'github-output'
        with patch.object(ci, '__file__', str(self.repo/'scripts/ci_linux_runtime.py')), patch.dict(os.environ,GITHUB_OUTPUT=str(output)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ci.main(['collect','--preparation-sha256',self.preparation]),0)
        values = dict(line.split('=',1) for line in output.read_text().splitlines())
        self.assertEqual(set(values), {'report_sha256','server_sha256','managed_sha256'})
        self.assertTrue(all(ci.HEX.fullmatch(value) for value in values.values()))
    def test_copied_report_tamper_refused(self):
        self.ready(); copy = shutil.copyfile
        def corrupt(*args, **kwargs):
            result = copy(*args, **kwargs); Path(args[1]).write_text('{}'); return result
        with patch.object(ci.shutil, 'copyfile', side_effect=corrupt), self.assertRaises(ValueError): self.run_collect()
        self.assertFalse((self.dest/'runtime.env').exists())
if __name__ == '__main__': unittest.main()
