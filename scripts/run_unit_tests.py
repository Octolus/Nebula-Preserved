#!/usr/bin/env python3
"""Bounded, parallel unit suites. Never starts Docker, Unity, Steam or a game."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SUITES = {'backend': 'backend/tests', 'tooling': 'scripts', 'builder': 'mirror-server/tests',
                 'bundles': 'patcher/tools', 'harness': 'tests/native'}
SUITES = (*PYTHON_SUITES, 'panel', 'patcher')
MAX_JOBS = 5
EXPECTED_SKIPS = {
    'test_avatar_native_save.NativeWriterFixture.test_available_native_exports_match_pinned_hashes_and_actual_writer_assignments':
        'Native work evidence is not distributed with backend',
    'test_shop_seed.LocalShopSeed.test_shop_card_urls_slice_to_shipped_resource_sprites':
        'Private extracted resource sprite inventory is not redistributed',
    'test_wardrobe_removal.WardrobeRemoval.test_every_control_is_bound_to_exact_shipped_manifest_evidence':
        'Private extracted bundle manifests are not redistributed; native provenance test',
}


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.durations = []

    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()

    def stopTest(self, test):
        self.durations.append({'test': test.id(), 'seconds': round(time.perf_counter() - self.started, 6)})
        super().stopTest(test)


def summarize(result, suite, elapsed):
    skipped = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
    unexpected = [row for row in skipped if suite != 'backend' or
                  EXPECTED_SKIPS.get(row['test']) != row['reason']]
    return {'suite': suite, 'tests_run': result.testsRun, 'seconds': round(elapsed, 3),
            'failures': len(result.failures), 'errors': len(result.errors),
            'expected_failures': len(result.expectedFailures), 'skipped': skipped,
            'unexpected_skips': unexpected,
            'slowest': sorted(result.durations, key=lambda row: (-row['seconds'], row['test']))[:10],
            'passed': bool(result.testsRun and result.wasSuccessful() and not unexpected
                           and not result.expectedFailures)}


def worker(suite, output, pattern):
    started = time.perf_counter()
    tests = unittest.defaultTestLoader.discover(str(ROOT / PYTHON_SUITES[suite]), pattern=pattern)
    result = unittest.TextTestRunner(verbosity=1, resultclass=TimedResult).run(tests)
    report = summarize(result, suite, time.perf_counter() - started)
    Path(output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1


def command(suite, output, pattern):
    if suite in PYTHON_SUITES:
        return [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', suite,
                '--worker-output', str(output), '--pattern', pattern], ROOT
    if suite == 'panel':
        executable = shutil.which('node')
        if executable is None:
            raise ValueError('Node.js is required for --suite panel (Node 24 recommended)')
        files = sorted((ROOT / 'admin-panel/tests').glob('*.test.ts'))
        if not files:
            raise ValueError('No panel unit tests found')
        return [executable, '--experimental-strip-types', '--test', '--test-reporter=tap',
                *[str(path) for path in files]], ROOT / 'admin-panel'
    if suite == 'patcher':
        executable = shutil.which('cargo')
        if executable is None:
            raise ValueError('Rust/Cargo is required for --suite patcher')
        # Never downloads dependencies as an implicit side effect of testing.
        return [executable, 'test', '--locked', '--offline'], ROOT / 'patcher'
    raise ValueError('Unknown unit suite')


def external_summary(suite, output):
    if suite == 'panel':
        metrics = {}
        for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
            values = re.findall(r'^# ' + key + r' (\d+)\s*$', output, re.MULTILINE)
            if len(values) != 1:
                raise ValueError('Missing or ambiguous Node test summary')
            metrics[key] = int(values[0])
        return {'tests_run': metrics['tests'], 'skipped': [], 'slowest': [],
                'passed': metrics['tests'] > 0 and metrics['pass'] == metrics['tests']
                and all(metrics[key] == 0 for key in ('fail', 'cancelled', 'skipped', 'todo'))}
    summaries = re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                           r'(\d+) measured; (\d+) filtered out;', output, re.MULTILINE)
    if not summaries:
        raise ValueError('Missing Cargo test summary')
    return {'tests_run': sum(int(row[1]) + int(row[2]) + int(row[3]) for row in summaries),
            'skipped': [], 'slowest': [],
            'passed': sum(int(row[1]) for row in summaries) > 0
            and all(row[0] == 'ok' and all(int(value) == 0 for value in row[2:]) for row in summaries)}


def run_suite(suite, directory, timeout, pattern):
    started = time.perf_counter()
    output = Path(directory) / (suite + '.json')
    completed = None
    try:
        argv, cwd = command(suite, output, pattern)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
        scratch = Path(directory) / (suite + '-tmp')
        scratch.mkdir(mode=0o700)
        environment.update({key: str(scratch) for key in ('TMPDIR', 'TMP', 'TEMP')})
        completed = subprocess.run(argv, cwd=cwd, env=environment, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                   check=False)
        if suite in PYTHON_SUITES:
            if not output.is_file():
                raise ValueError('Unit worker did not produce its result')
            report = json.loads(output.read_text(encoding='utf-8'))
            if report.get('suite') != suite or type(report.get('tests_run')) is not int or report['tests_run'] <= 0:
                raise ValueError('Invalid or empty unit worker result')
            report['passed'] = completed.returncode == 0 and report.get('passed') is True
        else:
            report = {'suite': suite, **external_summary(suite, completed.stdout)}
            report['passed'] = completed.returncode == 0 and report['passed']
        report.update(exit_code=completed.returncode,
                      wall_seconds=round(time.perf_counter() - started, 3),
                      stdout=completed.stdout, stderr=completed.stderr)
        return report
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        report = {'suite': suite, 'passed': False, 'wall_seconds': round(time.perf_counter() - started, 3),
                  'error': 'Suite timed out' if isinstance(error, subprocess.TimeoutExpired) else str(error)}
        if completed is not None:
            report.update(stdout=completed.stdout, stderr=completed.stderr)
        elif isinstance(error, subprocess.TimeoutExpired):
            for field in ('stdout', 'stderr'):
                value = getattr(error, field, None)
                if value:
                    report[field] = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
        return report


def temporary_base(disk_temp=False):
    # Only disposable fixtures use shared memory. Never changes server SQLite
    # pragmas, source paths, state directories or a community volume.
    candidate = Path('/dev/shm')
    if not disk_temp and sys.platform == 'linux' and candidate.is_dir():
        try:
            if os.access(candidate, os.W_OK) and shutil.disk_usage(candidate).free >= 128 * 1024 * 1024:
                return candidate
        except OSError:
            pass
    return None


def execute(suites, jobs=3, timeout=180, pattern='test*.py', on_result=None, disk_temp=False):
    if not suites or any(suite not in SUITES for suite in suites):
        raise ValueError('Choose at least one known suite')
    if not 1 <= jobs <= MAX_JOBS or not 1 <= timeout <= 900:
        raise ValueError('Jobs must be 1–5 and timeout 1–900 seconds')
    selected = list(dict.fromkeys(suites))
    started = time.perf_counter()
    base = temporary_base(disk_temp)
    with tempfile.TemporaryDirectory(prefix='nbu-', dir=base) as directory:
        with ThreadPoolExecutor(max_workers=min(jobs, len(selected))) as pool:
            futures = [pool.submit(run_suite, suite, directory, timeout, pattern) for suite in selected]
            completed = {}
            for future in as_completed(futures):
                result = future.result()
                completed[result['suite']] = result
                if on_result is not None:
                    on_result(result)
            results = [completed[suite] for suite in selected]
    return {'format': 'nebula-unit-results-v1', 'passed': all(row['passed'] for row in results),
            'wall_seconds': round(time.perf_counter() - started, 3), 'suites': results,
            'temporary_storage': 'shared-memory' if base is not None else 'os-temporary-directory'}


def show_result(row, durations):
    label = 'PASS' if row['passed'] else 'FAIL'
    count = f"  {row['tests_run']} tests, {len(row['skipped'])} evidence skips" if 'tests_run' in row else ''
    print(f"{label:4} {row['suite']:8} {row['wall_seconds']:7.2f}s" + count, flush=True)
    for skip in row.get('skipped', []):
        print('  SKIP ' + skip['test'] + ': ' + skip['reason'], flush=True)
    for test in row.get('slowest', [])[:durations]:
        print(f"  {test['seconds']:.3f}s {test['test']}", flush=True)
    if not row['passed']:
        for field in ('error', 'stdout', 'stderr'):
            if row.get(field):
                print(row[field], flush=True)
        for skip in row.get('unexpected_skips', []):
            print('UNEXPECTED SKIP: ' + skip['test'], flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument('--suite', choices=SUITES, action='append', help='Repeat to select suites; default: five Python suites')
    selected.add_argument('--all', action='store_true', help='Also test the panel and Rust patcher; requires Node and cached Cargo dependencies')
    parser.add_argument('--jobs', type=int, choices=range(1, MAX_JOBS + 1), default=3)
    parser.add_argument('--timeout', type=int, default=180, help='Per-suite deadline in seconds (1–900)')
    parser.add_argument('--disk-temp', action='store_true', help='Use OS temporary storage instead of Linux shared memory')
    parser.add_argument('--pattern', default='test*.py', help='Python filename filter; requires one explicit Python suite')
    parser.add_argument('--report', type=Path, help='Optional JSON report; prefer ignored test-results/unit.json')
    parser.add_argument('--durations', type=int, choices=range(0, 11), default=3, help='Slowest tests printed per Python suite')
    parser.add_argument('--worker', choices=tuple(PYTHON_SUITES), help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if args.worker_output is None:
            parser.error('An internal worker result path is required')
        return worker(args.worker, args.worker_output, args.pattern)
    if not 1 <= args.timeout <= 900:
        parser.error('--timeout must be 1–900 seconds')
    if args.pattern != 'test*.py' and (not args.suite or len(args.suite) != 1 or args.suite[0] not in PYTHON_SUITES):
        parser.error('--pattern requires one explicit Python --suite')
    selected = SUITES if args.all else args.suite or tuple(PYTHON_SUITES)
    print('Running unit suites: ' + ', '.join(selected), flush=True)
    report = execute(selected, args.jobs, args.timeout, args.pattern,
                     on_result=lambda row: show_result(row, args.durations), disk_temp=args.disk_temp)
    print(f"Total wall time: {report['wall_seconds']:.2f}s ({report['temporary_storage']})")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
