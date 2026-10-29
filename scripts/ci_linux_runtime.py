#!/usr/bin/env python3
"""Prepare and collect a hosted Unity compile; never launch the built server."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import uuid

WRAPPER = 'UnityProject/Assets/Editor/PreservationCIBuild.cs'
HEX = re.compile(r'[0-9a-f]{64}')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok, message):
    if not ok: raise ValueError(message)
def write_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream: stream.write(json.dumps(value, indent=2) + '\n')
def load_json(path):
    require(0 < path.stat().st_size <= 131072, 'CI JSON size differs')
    return json.loads(path.read_text(encoding='utf-8-sig'))
def helper(root, expected=None):
    path = root / 'mirror-server/build_linux.py'
    require(expected is None or digest(path) == expected, 'Build helper changed')
    spec = importlib.util.spec_from_file_location('nebula_existing_linux_builder', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.checked_path(path); return module
def paths(repo):
    root = repo / 'mirror-server'
    return root, root / 'ci-source-before.json', root / 'ci-build-receipt.json', repo / 'deployment/docker/private-linux'
def inputs(module, root, prep):
    require(module.source_hashes(root) == prep['source_hashes'] and
            module.sha256(root / WRAPPER) == prep['wrapper_sha256'] and
            module.sha256(root / 'build_linux.py') == prep['build_helper_sha256'], 'CI source closure changed')
def prepare(repo):
    root, before, receipt, destination = paths(repo); module = helper(repo)
    for path in (before, receipt, root / 'build-linux', root / 'build-linux-validation.json', root / '.build-linux.lock', destination):
        module.checked_path(path, missing=True, directory=path in (root / 'build-linux', destination))
        require(not path.exists(), 'CI output already exists: ' + path.name)
    value = {'format_version': 1, 'nonce': uuid.uuid4().hex, 'unity_editor': module.EDITOR_VERSION,
             'source_hashes': module.source_hashes(root), 'wrapper_sha256': module.sha256(root / WRAPPER),
             'build_helper_sha256': module.sha256(root / 'build_linux.py')}
    require(len(value['source_hashes']) == 21, 'Expected original 21-source closure')
    write_json(before, value); return {'preparation_sha256': module.sha256(before)}
def artifacts(module, folder):
    return [{'path': path.relative_to(folder).as_posix(), 'size': path.stat().st_size,
             'sha256': module.sha256(path)} for path in module.tree_files(folder)]
def collect(repo, preparation_sha256):
    root, before, receipt_path, destination = paths(repo)
    require(HEX.fullmatch(preparation_sha256) and digest(before) == preparation_sha256, 'Preparation SHA differs')
    prep = load_json(before); module = helper(repo, prep['build_helper_sha256'])
    module.checked_path(before); module.checked_path(receipt_path); inputs(module, root, prep)
    require(set(prep) == {'format_version', 'nonce', 'unity_editor', 'source_hashes', 'wrapper_sha256', 'build_helper_sha256'} and
            type(prep['format_version']) is int and prep['format_version'] == 1 and
            re.fullmatch(r'[0-9a-f]{32}', prep['nonce']) and prep['unity_editor'] == module.EDITOR_VERSION,
            'Preparation schema/editor differs')
    receipt_pin = module.sha256(receipt_path); receipt = load_json(receipt_path)
    require(set(receipt) == {'format_version', 'nonce', 'preparation_sha256', 'unity_editor', 'source_hashes_before',
            'source_hashes_after', 'wrapper_sha256', 'success_marker', 'marker_observed', 'original_returned'} and
            type(receipt['format_version']) is int and receipt['format_version'] == 1 and
            receipt['nonce'] == prep['nonce'] and receipt['preparation_sha256'] == preparation_sha256 and
            receipt['unity_editor'] == module.EDITOR_VERSION and receipt['wrapper_sha256'] == prep['wrapper_sha256'] and
            receipt['source_hashes_before'] == receipt['source_hashes_after'] == prep['source_hashes'] and
            receipt['marker_observed'] is True and receipt['original_returned'] is True and
            receipt['success_marker'] == module.MARKER, 'Original Unity success receipt differs')
    output = root / 'build-linux'; report_path = root / 'build-linux-validation.json'
    for path in (report_path, destination):
        module.checked_path(path, missing=True, directory=path == destination)
        require(not path.exists(), 'Collection output already exists')
    module.validate_elf(output / 'NebulaServer.x86_64')
    module.checked_path(output / 'NebulaServer_Data/Managed/Assembly-CSharp.dll')
    rows = artifacts(module, output); by_path = {row['path']: row for row in rows}; inputs(module, root, prep)
    report = {'kind': 'compile_only_linux_dedicated_server_build',
        'utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'unity_editor': module.EDITOR_VERSION,
        'exit_code': 0, 'success_marker': module.MARKER, 'target': 'StandaloneLinux64', 'subtarget': 'Server',
        'scripting_backend': 'Mono2x', 'elf64_x86_64': True, 'game_launched': False,
        'reconstructed_listener_started': False, 'linux_runtime_tested': False, 'sources_unchanged_during_build': True,
        'source_hashes': prep['source_hashes'], 'artifacts': rows,
        'executable_sha256': by_path['NebulaServer.x86_64']['sha256'],
        'managed_assembly_sha256': by_path['NebulaServer_Data/Managed/Assembly-CSharp.dll']['sha256'],
        'networking_parity_proven': False}
    write_json(report_path, report); destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(output, destination / 'build'); shutil.copyfile(report_path, destination / report_path.name)
    require(artifacts(module, destination / 'build') == rows and artifacts(module, output) == rows and
            module.sha256(destination / report_path.name) == module.sha256(report_path), 'Artifact tree/report changed during collection')
    inputs(module, root, prep)
    require(module.sha256(before) == preparation_sha256 and module.sha256(receipt_path) == receipt_pin, 'CI receipts changed during collection')
    values = {'report_sha256': module.sha256(report_path), 'server_sha256': report['executable_sha256'],
              'managed_sha256': report['managed_assembly_sha256']}
    with (destination / 'runtime.env').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('NEBULA_BUILD_REPORT_SHA256=' + values['report_sha256'] + '\nNEBULA_SERVER_SHA256=' +
                     values['server_sha256'] + '\nNEBULA_MANAGED_SHA256=' + values['managed_sha256'] + '\n')
    return values
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare'); child = sub.add_parser('collect'); child.add_argument('--preparation-sha256', required=True)
    args = parser.parse_args(argv); repo = Path(__file__).resolve().parents[1]
    try: values = prepare(repo) if args.command == 'prepare' else collect(repo, args.preparation_sha256)
    except (ValueError, OSError, KeyError, TypeError) as exc: parser.exit(1, 'CI runtime collection failed: ' + str(exc) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
            stream.writelines(key + '=' + value + '\n' for key, value in values.items())
    print(json.dumps(values)); return 0
if __name__ == '__main__': raise SystemExit(main())
