"""Runner failures, empty discovery, skip policy and process isolation, offline."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('unit_runner', Path(__file__).with_name('run_unit_tests.py'))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def report(self, **kwargs):
        return {'suite': 'backend', 'passed': True, 'tests_run': 1, **kwargs}

    def fake_result(self, **kwargs):
        return SimpleNamespace(testsRun=1, failures=[], errors=[], expectedFailures=[], skipped=[],
            durations=[], wasSuccessful=lambda: True, **kwargs)

    def test_zero_tests_unexpected_skips_and_expected_failures_fail_closed(self):
        zero = self.fake_result()
        zero.testsRun = 0
        self.assertFalse(runner.summarize(zero, 'backend', 0)['passed'])
        skipped = self.fake_result()
        skipped.skipped = [(SimpleNamespace(id=lambda: 'unexpected.test'), 'disabled')]
        report = runner.summarize(skipped, 'backend', 0)
        self.assertFalse(report['passed'])
        self.assertEqual(len(report['unexpected_skips']), 1)
        expected_failure = self.fake_result()
        expected_failure.expectedFailures = [('broken', 'trace')]
        self.assertFalse(runner.summarize(expected_failure, 'backend', 0)['passed'])

    def test_only_exact_private_evidence_skip_id_reason_and_suite_are_allowed(self):
        name, reason = next(iter(runner.EXPECTED_SKIPS.items()))
        result = self.fake_result()
        result.skipped = [(SimpleNamespace(id=lambda: name), reason)]
        self.assertTrue(runner.summarize(result, 'backend', 0)['passed'])
        self.assertFalse(runner.summarize(result, 'tooling', 0)['passed'])
        result.skipped[0] = (result.skipped[0][0], 'another reason')
        self.assertFalse(runner.summarize(result, 'backend', 0)['passed'])

    def test_python_worker_never_uses_shell_and_preserves_deterministic_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'backend.json'
            def execute(argv, **kwargs):
                self.assertEqual(argv[0], runner.sys.executable)
                self.assertIn('--worker', argv)
                self.assertEqual(kwargs['cwd'], runner.ROOT)
                self.assertEqual(kwargs['env']['PYTHONHASHSEED'], '0')
                self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
                self.assertEqual(kwargs['env']['TMPDIR'], str(Path(directory) / 'backend-tmp'))
                self.assertEqual(kwargs['env']['TEMP'], kwargs['env']['TMPDIR'])
                self.assertEqual(kwargs['timeout'], 7)
                self.assertNotIn('shell', kwargs)
                output.write_text(json.dumps(self.report()))
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch.object(runner.subprocess, 'run', side_effect=execute):
                self.assertTrue(runner.run_suite('backend', directory, 7, 'test*.py')['passed'])

    def test_nonzero_exit_cannot_be_hidden_by_a_passing_worker_report(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'backend.json').write_text(json.dumps(self.report()))
            completed = SimpleNamespace(returncode=1, stdout='failure output', stderr='failure trace')
            with patch.object(runner.subprocess, 'run', return_value=completed):
                result = runner.run_suite('backend', directory, 2, 'test*.py')
            self.assertFalse(result['passed'])
            self.assertEqual(result['stderr'], 'failure trace')

    def test_missing_corrupt_mismatched_and_empty_reports_fail_with_diagnostics(self):
        invalid = (None, '{', json.dumps(self.report(suite='other')), json.dumps(self.report(tests_run=0)))
        for content in invalid:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                if content is not None:
                    (Path(directory) / 'backend.json').write_text(content)
                completed = SimpleNamespace(returncode=0, stdout='', stderr='worker diagnostic')
                with patch.object(runner.subprocess, 'run', return_value=completed):
                    result = runner.run_suite('backend', directory, 2, 'test*.py')
                self.assertFalse(result['passed'])
                self.assertEqual(result['stderr'], 'worker diagnostic')

    def test_timeout_and_missing_tool_are_failures_without_implicit_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('unit', 1)):
                result = runner.run_suite('backend', directory, 1, 'test*.py')
                self.assertEqual(result['error'], 'Suite timed out')
            with patch.object(runner.shutil, 'which', return_value=None), \
                 patch.object(runner.subprocess, 'run') as run:
                for suite in ('panel', 'patcher'):
                    self.assertFalse(runner.run_suite(suite, directory, 1, 'test*.py')['passed'])
                run.assert_not_called()

    def test_parallel_suites_are_bounded_deduplicated_and_reported_in_selection_order(self):
        barrier = threading.Barrier(2)
        active = []
        def execute(suite, directory, timeout, pattern):
            active.append(suite)
            barrier.wait(timeout=3)
            return {'suite': suite, 'passed': suite != 'builder'}
        with patch.object(runner, 'run_suite', side_effect=execute):
            report = runner.execute(['backend', 'builder', 'backend'], jobs=2)
        self.assertCountEqual(active, ['backend', 'builder'])
        self.assertEqual([row['suite'] for row in report['suites']], ['backend', 'builder'])
        self.assertFalse(report['passed'])

    def test_invalid_suite_jobs_timeout_and_pattern_fail_before_execution(self):
        for suites, jobs, timeout in (([], 1, 1), (['unknown'], 1, 1), (['backend'], 0, 1),
                                      (['backend'], 6, 1), (['backend'], 1, 0), (['backend'], 1, 901)):
            with self.subTest(suites=suites, jobs=jobs, timeout=timeout), self.assertRaises(ValueError):
                runner.execute(suites, jobs, timeout)
        with patch.object(runner, 'execute') as execute, patch('sys.stderr', new_callable=io.StringIO):
            for argv in (['--pattern', 'test_edge*.py'], ['--suite', 'panel', '--pattern', '*'], ['--timeout', '0']):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as got:
                    runner.main(argv)
                self.assertEqual(got.exception.code, 2)
            execute.assert_not_called()

    def test_external_commands_are_unit_only_and_cargo_is_locked_and_offline(self):
        with patch.object(runner.shutil, 'which', side_effect=lambda name: name):
            cargo, cwd = runner.command('patcher', None, 'test*.py')
            self.assertEqual(cargo, ['cargo', 'test', '--locked', '--offline'])
            self.assertEqual(cwd, runner.ROOT / 'patcher')
            panel, cwd = runner.command('panel', None, 'test*.py')
            self.assertIn('--test', panel)
            self.assertNotIn('playwright', panel)
            self.assertEqual(cwd, runner.ROOT / 'admin-panel')

    def test_external_summaries_reject_zero_tests_skips_and_missing_or_ambiguous_counts(self):
        tap = '# tests 2\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n'
        self.assertTrue(runner.external_summary('panel', tap)['passed'])
        for text in (tap.replace('tests 2', 'tests 0'), tap.replace('skipped 0', 'skipped 1'),
                     tap.replace('todo 0', 'todo 1')):
            self.assertFalse(runner.external_summary('panel', text)['passed'])
        for text in ('', tap + '# tests 2\n'):
            with self.assertRaises(ValueError):
                runner.external_summary('panel', text)
        cargo = 'test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n'
        self.assertTrue(runner.external_summary('patcher', cargo)['passed'])
        for text in (cargo.replace('2 passed', '0 passed'), cargo.replace('0 ignored', '1 ignored'),
                     cargo.replace('ok.', 'FAILED.'), cargo.replace('0 filtered out', '1 filtered out')):
            self.assertFalse(runner.external_summary('patcher', text)['passed'])
        with self.assertRaises(ValueError):
            runner.external_summary('patcher', 'build complete')

    def test_shared_memory_requires_linux_writable_capacity_and_can_be_disabled(self):
        with patch.object(runner.sys, 'platform', 'linux'), \
             patch.object(runner.Path, 'is_dir', return_value=True), \
             patch.object(runner.os, 'access', return_value=True), \
             patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=256 * 1024 * 1024)):
            self.assertEqual(runner.temporary_base(), Path('/dev/shm'))
            self.assertIsNone(runner.temporary_base(disk_temp=True))
            with patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=64 * 1024 * 1024)):
                self.assertIsNone(runner.temporary_base())
            with patch.object(runner.os, 'access', return_value=False):
                self.assertIsNone(runner.temporary_base())
            with patch.object(runner.shutil, 'disk_usage', side_effect=OSError('unavailable')):
                self.assertIsNone(runner.temporary_base())
            with patch.object(runner.sys, 'platform', 'win32'):
                self.assertIsNone(runner.temporary_base())


if __name__ == '__main__':
    unittest.main()
