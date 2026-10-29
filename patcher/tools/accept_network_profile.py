"""Offline CLI fixtures only. Fake helpers and game targets MUST NEVER execute.

Reads owned pristine Steam inputs; writes only a new external private directory.
Child LOCALAPPDATA is isolated. Remote configs are synthetic containers, not a
TLS/DPAPI/native-transport acceptance test. The patcher never contacts a server.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

BASE = {
    'GameAssembly.dll': 'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac',
    'Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat': 'c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1',
    'Nebula Realms_Data/globalgamemanagers': 'ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466',
    'Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor': '5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0',
}
EXE = '77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d'
HELPERS = ('NebulaRegistryBridge.dll', 'NebulaNetworkBridge.dll', 'NebulaPublicAccess.dll', 'steam_appid.txt')
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def require(ok, reason):
    if not ok:
        raise AssertionError(reason)


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def main(args):
    originals = args.originals.resolve(strict=True)
    tool = args.patcher.resolve(strict=True)
    out = args.output.resolve()
    source = Path(__file__).resolve().parents[1]
    require(not out.exists() and not out.is_relative_to(source) and not out.is_relative_to(originals)
            and 'steamapps' not in [p.lower() for p in out.parts], 'NEW external fixture outside source/Steam required')
    pins = {**BASE, 'Nebula Realms.exe': EXE}
    for name, pin in pins.items():
        require(sha((originals / name).read_bytes()) == pin, 'Unsupported pristine input ' + name)
    out.mkdir(parents=True)
    game = out / 'fixture-game-DO-NOT-EXECUTE'
    game.mkdir()
    for name in pins:
        write(game / name, (originals / name).read_bytes())
    # The pre-existing empty lock is included in every rejection snapshot.
    write(game / '.nebula-preservation.lock', b'')
    cases = []
    private = out / 'isolated-localappdata'
    private.mkdir()
    env = dict(os.environ, LOCALAPPDATA=str(private), PYTHONDONTWRITEBYTECODE='1')

    def command(argv, success=True, contains=None, executable=tool):
        p = subprocess.run([str(executable), *map(str, argv)], env=env, capture_output=True, text=True, timeout=180)
        require((p.returncode == 0) == success, p.stdout + p.stderr)
        if contains:
            require(contains in p.stdout + p.stderr, 'Missing diagnostic ' + contains + ': ' + p.stdout + p.stderr)
        cases.append({'arguments': list(map(str, argv)), 'exit_code': p.returncode,
                      'stdout': p.stdout, 'stderr': p.stderr})
        return p

    def config(server):
        folder = private / 'NebulaPreservation'
        folder.mkdir(exist_ok=True)
        token = folder / 'account-token.dpapi'
        body = b'SYNTHETIC-NON-DPAPI-FIXTURE'
        write(token, b'NPA1' + struct.pack('<I', len(body)) + body)
        write(folder / 'public-access.conf',
              f'format=nebula-public-access-v1\nserver_url={server}\ntoken_file={token}\n'.encode())
        ca = folder / 'operator-ca.der'
        write(ca, b'\x30\x02\x05\x00')
        write(folder / 'remote-game.conf', (f'format=nebula-remote-transport-v1\nserver_url={server}\n'
              f'gateway_port=8443\napi_port=38080\nfirst_scene_port=28000\nlast_scene_port=28031\n'
              f'ca_file={ca}\nca_sha256={sha(ca.read_bytes())}\n').encode())

    ga = (originals / 'GameAssembly.dll').read_bytes()
    metadata = next(p for p in BASE if p.endswith('global-metadata.dat'))
    editor = next(p for p in BASE if p.endswith('charactereditor'))
    view = out / 'editor-view.PRIVATE'
    command(['bundle-view', '--input', originals / editor, '--output', view])
    views = {name: (view.read_bytes() if name == editor else (originals / name).read_bytes()) for name in BASE}
    bundles = {}

    # Exercise the real production builder for both six and seven-artifact sets.
    for label, remote in [('A', False), ('R', True)]:
        targets = out / ('targets-' + label)
        target = ga + ('AUTHORED-OFFLINE-' + label).encode()
        write(targets / 'ga.fixture', target)
        artifacts = [{'path': 'GameAssembly.dll', 'target': str(targets / 'ga.fixture'), 'target_sha256': sha(target)},
                     {'path': metadata}]
        for name in HELPERS + (('NebulaRemoteTransport.exe',) if remote else ()):
            raw = b'919290' if name == 'steam_appid.txt' else ('NONEXECUTABLE-OFFLINE-' + name + label).encode()
            write(targets / (name + '.fixture'), raw)
            artifacts.append({'path': name, 'target': str(targets / (name + '.fixture')), 'target_sha256': sha(raw)})
        plan = {'format': 'nebula-release-input-v1', 'app_id': '919290', 'build_id': '11018722',
                'profile': 'network-only', 'status': 'provisional', 'review': 'Offline fake targets MUST NEVER execute.',
                'originals': str(originals), 'artifacts': artifacts}
        plan_path = out / ('plan-' + label + '.json')
        write(plan_path, json.dumps(plan, indent=2).encode())
        folder = out / ('bundle-' + label)
        command([source / 'tools/build_bundle.py', '--plan', plan_path, '--patcher', tool, '--output', folder], executable=sys.executable)
        bundles[label] = folder

    # A second direct target and legacy profile exercise update/transition policy.
    for label, legacy in [('B', False), ('L', True)]:
        folder = out / ('bundle-' + label)
        folder.mkdir()
        artifacts = []
        names = list(BASE) if legacy else list(BASE)[:2]
        for index, name in enumerate(names):
            entry = dict(path=name, operation='metadata', original_sha256=BASE[name], accepted_existing=[],
                         payload=None, payload_sha256=None, payload_size=None, source_view_sha256=None, output_sha256=None)
            if name != metadata:
                data = views[name]
                extra = ('AUTHORED-OFFLINE-' + label).encode()
                target = data + extra
                delta = b'NBD1' + struct.pack('<IQ', 2, len(target)) + b'\0' + struct.pack('<QQ', 0, len(data)) + b'\1' + struct.pack('<Q', len(extra)) + extra
                payload = f'payloads/{index}.nbd'
                write(folder / payload, delta)
                entry.update(operation='unityfs_delta' if name == editor else 'delta', payload=payload,
                             payload_sha256=sha(delta), payload_size=len(delta), source_view_sha256=sha(data), output_sha256=sha(target))
            artifacts.append(entry)
        for name in (('NebulaRegistryBridge.dll', 'NebulaAutomation.dll', 'NebulaPublicAccess.dll', 'steam_appid.txt') if legacy else HELPERS):
            raw = b'919290' if name == 'steam_appid.txt' else ('NONEXECUTABLE-OFFLINE-' + name + label).encode()
            payload = 'payloads/' + name + '.fixture'
            write(folder / payload, raw)
            artifacts.append(dict(path=name, operation='owned_file', original_sha256=None, accepted_existing=[], payload=payload,
                                  payload_sha256=sha(raw), payload_size=len(raw), source_view_sha256=None, output_sha256=sha(raw)))
        manifest = dict(format='nebula-patch-v1', app_id='919290', build_id='11018722', status='provisional',
                        review='Nonexecuting offline fixture', artifacts=artifacts)
        if not legacy:
            manifest['profile'] = 'network-only'
        write(folder / 'manifest.json', json.dumps(manifest, indent=2).encode())
        bundles[label] = folder

    state = game / '.nebula-preservation'
    receipt_path = state / 'receipt.json'

    def snapshot():
        return {p.relative_to(game).as_posix(): sha(p.read_bytes()) for p in game.rglob('*') if p.is_file()}

    def receipt():
        return json.loads(receipt_path.read_bytes())

    def patch(label, server='http://127.0.0.1:8080', remote=False, dry=False, success=True, contains=None):
        folder = bundles[label]
        argv = ['patch', '--game', game, '--bundle', folder, '--manifest-sha256', sha((folder / 'manifest.json').read_bytes()),
                '--server', server, '--advertise-ip', '127.0.0.1', '--allow-provisional']
        if remote:
            argv.append('--remote-transport')
        if dry:
            argv.append('--dry-run')
        before = snapshot() if dry or not success else None
        command(argv, success, contains)
        if before is not None:
            require(snapshot() == before, 'Rejected/dry-run command changed fixture files')
        if success and not dry:
            for e in receipt()['entries']:
                require(sha((game / e['path']).read_bytes()) == e['after'], 'Installed receipt mismatch')
            if label != 'L':
                for path in list(BASE)[2:]:
                    require(sha((game / path).read_bytes()) == BASE[path], 'Strict profile changed optional originals')
                require(not (game / 'NebulaAutomation.dll').exists(), 'Strict profile left automation DLL')

    def restore():
        command(['restore', '--game', game])

    def pristine():
        for name, pin in pins.items():
            require(sha((game / name).read_bytes()) == pin, 'Restore failed exact original ' + name)
        for name in HELPERS + ('NebulaAutomation.dll', 'NebulaRemoteTransport.exe'):
            require(not (game / name).exists(), 'Restore left fake helper ' + name)
        require(not receipt_path.exists(), 'Restore left active receipt')

    patch('A', dry=True)
    require(not state.exists(), 'Dry run created state')
    patch('A')
    require(len(receipt()['entries']) == 6, 'Not six entries')
    require([e['path'] for e in receipt()['entries']].index('NebulaNetworkBridge.dll') < [e['path'] for e in receipt()['entries']].index('GameAssembly.dll'), 'Wrong dependency order')
    patch('A', 'http://127.0.0.1:8081')
    patch('B', 'http://127.0.0.1:8082')
    patch('B', 'http://127.0.0.1:8082', contains='Already installed')
    patch('L', success=False, contains='Restore the network-only profile')
    r = receipt();e = next(x for x in r['entries'] if x['path'] == 'GameAssembly.dll')
    backup = state / e['backup'];raw = backup.read_bytes();write(backup, raw + b'tamper')
    patch('A', 'http://127.0.0.1:8083', dry=True, success=False, contains='Historical backup pin mismatch');write(backup, raw)
    bridge = game / 'NebulaNetworkBridge.dll';raw = bridge.read_bytes();write(bridge, b'tamper')
    patch('A', 'http://127.0.0.1:8083', dry=True, success=False, contains='Installed file changed since receipt');write(bridge, raw)
    saved = receipt_path.read_bytes();r['entries'][-1]['after'] = sha(b'stale');write(receipt_path, json.dumps(r).encode())
    patch('A', 'http://127.0.0.1:8083', dry=True, success=False, contains='Installed file changed since receipt');write(receipt_path, saved)
    restore();restore();restore();pristine()

    patch('L');patch('A', success=False, contains='Restore the previous client profile')
    patch('L', 'http://127.0.0.1:8081');restore();restore();pristine()
    optional = game / list(BASE)[2];raw = optional.read_bytes();write(optional, raw + b'old-input-patch')
    patch('A', success=False, contains='pristine optional input/editor');write(optional, raw)
    write(game / 'NebulaAutomation.dll', b'old-automation')
    patch('A', success=False, contains='cannot retain NebulaAutomation.dll');(game / 'NebulaAutomation.dll').unlink()

    folder = bundles['A'];manifest = json.loads((folder / 'manifest.json').read_bytes());saved = (folder / 'manifest.json').read_bytes()
    variations = []
    for path in HELPERS + ('GameAssembly.dll', metadata):
        bad = json.loads(saved);bad['artifacts'] = [a for a in bad['artifacts'] if a['path'] != path];variations.append(bad)
    bad = json.loads(saved);bad['artifacts'][2]['path'] = 'NebulaAutomation.dll';variations.append(bad)
    bad = json.loads(saved);bad.pop('profile');variations.append(bad)
    bad = json.loads(saved);bad['profile'] = 'unknown';variations.append(bad)
    for bad in variations:
        write(folder / 'manifest.json', json.dumps(bad).encode());patch('A', success=False)
    write(folder / 'manifest.json', saved)
    payload = folder / manifest['artifacts'][2]['payload'];raw = payload.read_bytes();write(payload, raw + b'tamper')
    patch('A', success=False, contains='Payload pin mismatch');write(payload, raw)

    server = 'https://preservation.example.invalid';config(server)
    patch('R', server, success=False, contains='seventh transport artifact')
    patch('A', server, remote=True, success=False, contains='seventh transport artifact')
    patch('R', server, remote=True, dry=True);patch('R', server, remote=True)
    require(len(receipt()['entries']) == 7, 'Not seven entries')
    patch('A', success=False, contains='Restore the previous client profile')
    server2 = 'https://second.example.invalid';config(server2)
    previous_configuration = receipt()['configuration'];patch('R', server2, remote=True)
    require(receipt()['configuration'] != previous_configuration, 'Remote endpoint update not receipted')
    restore();restore();pristine()
    patch('A');config(server);patch('R', server, remote=True);restore();restore();pristine()
    for name, pin in pins.items():
        require(sha((originals / name).read_bytes()) == pin, 'Read-only originals changed')
    report = {'format': 'nebula-network-only-cli-fixture-v1', 'patcher_sha256': sha(tool.read_bytes()),
              'commands_passed': len(cases), 'cases': cases, 'actual_bundle_builder_six_and_seven': True,
              'fresh_six_and_seven_apply_repoint_restore': True, 'backup_resolution_preserved': True,
              'wrong_mixed_missing_artifacts_and_tampering_rejected': True,
              'legacy_to_network_and_reverse_requires_restore': True,
              'legacy_eight_endpoint_update_preserved': True, 'optional_core_bytes_preserved': True,
              'remote_to_direct_requires_restore': True, 'direct_to_remote_restores_exactly': True,
              'child_localappdata_isolated': True, 'synthetic_protected_container_not_real_dpapi': True,
              'native_or_transport_executed': False, 'network_contacted': False,
              'live_game_or_user_config_modified': False, 'readonly_originals_unchanged': True}
    path = out / 'acceptance-receipt.json'
    write(path, (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps({'commands_passed': len(cases), 'receipt_sha256': sha(path.read_bytes())}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('originals', 'patcher', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    main(parser.parse_args())
