"""Package the source-bound Linux server build; never deploy or start it."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

OUT = Path(__file__).resolve().parents[1]
RUNTIME_TOOLS = ('avatar_entry_codec.py', 'instance_supervisor.py', 'seed_local_shops.py')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def package(destination, out=OUT):
    destination = Path(destination).resolve()
    if destination.exists() or destination.suffix.lower() != '.zip':
        raise ValueError('Destination must be a new ZIP file')
    report_path = out/'mirror-server/build-linux-validation.json'
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    if (report.get('kind') != 'compile_only_linux_dedicated_server_build' or
            report.get('exit_code') != 0 or report.get('elf64_x86_64') is not True or
            report.get('sources_unchanged_during_build') is not True):
        raise ValueError('Successful source-bound Linux build report required')
    for record in report['source_hashes']:
        if sha(out/'mirror-server'/record['path']) != record['sha256']:
            raise ValueError('Stale build source: '+record['path'])
    for record in report['artifacts']:
        if sha(out/'mirror-server/build-linux'/record['path']) != record['sha256']:
            raise ValueError('Stale build artifact: '+record['path'])
    paths = []
    for directory in ('backend','protocol','deployment','mirror-server/build-linux'):
        paths += [p for p in (out/directory).rglob('*') if p.is_file() and
                  '__pycache__' not in p.parts and p.suffix != '.pyc' and
                  not (directory == 'backend' and 'tests' in p.relative_to(out).parts)]
    paths += [report_path, out/'mirror-server/provenance.json',
        out/'mirror-server/UnityProject/Assets/Mirror/LICENSE']
    paths += [out/'tools'/name for name in RUNTIME_TOOLS]
    # Reading all inputs before opening the output prevents partial archives on
    # missing inputs. Explicit new output never overwrites a prior package.
    content = [(str(p.relative_to(out)).replace('\\','/'),p.read_bytes()) for p in sorted(set(paths))]
    manifest = {'format_version':1,'kind':'linux_preservation_server_package',
        'target':'Linux x86-64 dedicated Mono server', 'deployed':False,
        'listeners_started':False,'linux_runtime_tested':False,'game_ready':False,
        'execution_flags_scope':'Packaging action only; prior runtime validation is recorded separately below.',
        'files':[{'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in content]}
    runtime_path = out/'deployment/linux-runtime-validation.json'
    if runtime_path.exists():
        runtime = json.loads(runtime_path.read_text(encoding='utf-8-sig'))
        manifest['prior_runtime_validation'] = {
            'path':'deployment/linux-runtime-validation.json','sha256':sha(runtime_path),
            'protocol_fixture_flow_passed':runtime.get('protocol_fixture_flow_passed'),
            'scope':runtime.get('scope'),
            'native_client_connected_to_linux_backend':runtime.get('native_client_connected_to_linux_backend'),
            'external_reachability_proven':runtime.get('external_reachability_proven')}
    native_runtime_path = out/'deployment/linux-native-runtime-validation.json'
    if native_runtime_path.exists():
        native_runtime = json.loads(native_runtime_path.read_text(encoding='utf-8-sig'))
        manifest['prior_native_runtime_validation'] = {
            'path':'deployment/linux-native-runtime-validation.json', 'sha256':sha(native_runtime_path),
            'native_client_connected_to_linux_backend':native_runtime.get('native_client_connected_to_linux_backend'),
            'native_public_chat_round_trip':native_runtime.get('native_public_chat_round_trip'),
            'external_reachability_proven':native_runtime.get('external_reachability_proven'),
            'two_native_clients_proven':native_runtime.get('two_native_clients_proven'),
            'scope':native_runtime.get('scope')}
    delta_path = out/'deployment/linux-postvalidation-source-delta.json'
    if delta_path.exists():
        manifest['post_native_run_source_delta'] = {
            'path':delta_path.relative_to(out).as_posix(), 'sha256':sha(delta_path),
            'scope':'Reward-absence policy changed after the native Linux run. Current Linux backend unit checks and Windows encrypted HTTP checks are recorded separately; no native Linux rerun is claimed.'}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in content:
            entry = zipfile.ZipInfo('nebula-preservation/'+name)
            entry.create_system = 3
            mode = 0o100755 if name == 'mirror-server/build-linux/NebulaServer.x86_64' else 0o100644
            entry.external_attr = mode << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry,data)
        archive.writestr('nebula-preservation/package-manifest.json',json.dumps(manifest,indent=2)+'\n')
    return {'path':str(destination),'sha256':sha(destination),'files':len(content),'deployed':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = package(args.destination)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))

if __name__ == '__main__': main()
