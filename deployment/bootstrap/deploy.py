"""Prepare or install a self-contained reviewed Linux Docker release.

The installer generates private deployment settings, installs its Ansible
dependency, then configures Docker, durable state, TLS and boot/renewal services.
It never embeds player credentials or treats server health as gameplay proof.
"""
import argparse
import hashlib
import ipaddress
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
HEX = re.compile(r'[0-9a-f]{64}')
IMAGE = re.compile(r'[A-Za-z0-9][A-Za-z0-9./:_@-]{0,255}')
NGINX = 'nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236'
PAYLOAD = (
    'deployment/bootstrap/deploy.py', 'deployment/bootstrap/README.md',
    'deployment/docker/compose.yaml', 'deployment/docker/compose.public.yaml',
    'deployment/docker/nginx-public.conf', 'deployment/tools/backup_state.py',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'Linked release paths are refused')
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'Release input must be a regular file')
    return path


def sha256(path):
    digest = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_json(path, limit=1024 * 1024):
    path = regular(path)
    require(path.stat().st_size <= limit, 'Release JSON exceeds size limit')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def safe_name(value):
    require(isinstance(value, str), 'Unsafe release member path')
    path = PurePosixPath(value)
    require(value and '\\' not in value and ':' not in value
            and not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/')),
            'Unsafe release member path')
    return value


def image_ids(archive, images):
    """Bind legacy/config and containerd/index identities to the selected image.

    Classic Docker reports the config digest as Image.Id. Containerd-backed
    Docker can report its tagged OCI index/manifest digest instead. Both must
    resolve to the exact archived Linux/amd64 config and ordered layer closure.
    """
    require(all(IMAGE.fullmatch(value) for value in images), 'Invalid image reference')
    with tarfile.open(regular(archive), mode='r:*') as stream:
        members = {}
        for member in stream:
            safe_name(member.name.rstrip('/') if member.isdir() else member.name)
            require(member.isfile() or member.isdir(), 'Linked/special image archive member refused')
            require(member.name not in members, 'Duplicate image archive member')
            members[member.name] = member
            require(len(members) <= 100000, 'Image archive contains too many members')
        manifest = members.get('manifest.json')
        require(manifest is not None and manifest.isfile() and manifest.size <= 1024 * 1024,
                'Expected bounded Docker save manifest.json')
        values = json.loads(stream.extractfile(manifest).read())
        require(isinstance(values, list) and 0 < len(values) <= 32, 'Invalid Docker save image list')
        found = {}
        for value in values:
            require(isinstance(value, dict) and isinstance(value.get('RepoTags'), (list, type(None))),
                    'Invalid Docker image tags')
            config = members.get(safe_name(value.get('Config', '')))
            require(config is not None and config.isfile() and config.size <= 1024 * 1024,
                    'Missing or oversized Docker image configuration')
            digest = 'sha256:' + hashlib.sha256(stream.extractfile(config).read()).hexdigest()
            config_value = json.loads(stream.extractfile(config).read())
            require(isinstance(config_value, dict) and config_value.get('architecture') == 'amd64'
                    and config_value.get('os') == 'linux',
                    'Docker image configuration must target Linux/amd64')
            layers = value.get('Layers')
            require(isinstance(layers, list) and len(layers) <= 256
                    and all(isinstance(name, str) and safe_name(name) in members
                            and members[name].isfile() for name in layers),
                    'Missing or invalid Docker image layers')
            for tag in value.get('RepoTags') or []:
                require(isinstance(tag, str), 'Invalid Docker image tag')
                identity = {'config': digest, 'layers': layers}
                require(tag not in found or found[tag] == identity, 'Ambiguous Docker image tag')
                found[tag] = identity

        indexes = ('application/vnd.oci.image.index.v1+json',
                   'application/vnd.docker.distribution.manifest.list.v2+json')
        manifests = ('application/vnd.oci.image.manifest.v1+json',
                     'application/vnd.docker.distribution.manifest.v2+json')
        checked = set()

        def blob(descriptor, decode=False):
            require(isinstance(descriptor, dict) and isinstance(descriptor.get('digest'), str)
                    and re.fullmatch(r'sha256:[0-9a-f]{64}', descriptor['digest'])
                    and type(descriptor.get('size')) is int and descriptor['size'] >= 0,
                    'Invalid OCI blob descriptor')
            name = 'blobs/sha256/' + descriptor['digest'].split(':')[1]
            member = members.get(name)
            require(member is not None and member.isfile() and member.size == descriptor['size'],
                    'Missing or wrong-size OCI blob')
            if descriptor['digest'] not in checked:
                digest = hashlib.sha256()
                with stream.extractfile(member) as content:
                    for block in iter(lambda: content.read(1024 * 1024), b''):
                        digest.update(block)
                require('sha256:' + digest.hexdigest() == descriptor['digest'], 'OCI blob digest mismatch')
                checked.add(descriptor['digest'])
            if decode:
                require(member.size <= 4 * 1024 * 1024, 'OCI metadata exceeds size limit')
                return json.loads(stream.extractfile(member).read())
            return name

        def closure(descriptor, expected, depth=0):
            require(depth <= 4, 'OCI index nesting exceeds limit')
            target = descriptor.get('platform', {}) if isinstance(descriptor, dict) else None
            require(isinstance(target, dict) and (not target or
                    (target.get('os') == 'linux' and target.get('architecture') == 'amd64')),
                    'OCI selected descriptor must target Linux/amd64')
            value = blob(descriptor, decode=True)
            require(isinstance(value, dict) and value.get('schemaVersion') == 2,
                    'Invalid OCI manifest schema')
            media = descriptor.get('mediaType')
            if media in indexes:
                children = value.get('manifests')
                require(isinstance(children, list) and len(children) <= 128, 'Invalid OCI index children')
                candidates = []
                for child in children:
                    require(isinstance(child, dict), 'Invalid OCI index descriptor')
                    target = child.get('platform', {})
                    require(isinstance(target, dict), 'Invalid OCI platform descriptor')
                    if ((target.get('os') == 'linux' and target.get('architecture') == 'amd64')
                            or (not target and child.get('mediaType') in indexes)):
                        candidates.append(child)
                require(len(candidates) == 1, 'OCI index needs one unambiguous Linux/amd64 image')
                closure(candidates[0], expected, depth + 1)
                return
            require(media in manifests, 'Unsupported OCI image descriptor type')
            config = value.get('config')
            config_value = blob(config, decode=True)
            require(config['digest'] == expected['config']
                    and isinstance(config_value, dict)
                    and config_value.get('architecture') == 'amd64' and config_value.get('os') == 'linux',
                    'OCI selected config differs from tagged Linux/amd64 Docker image')
            layers = value.get('layers')
            require(isinstance(layers, list) and len(layers) <= 256, 'Invalid OCI layer list')
            require([blob(layer) for layer in layers] == expected['layers'],
                    'OCI layer closure differs from tagged Docker image')

        def canonical(tag):
            parts = tag.split('/')
            if len(parts) == 1:
                return 'docker.io/library/' + tag
            if '.' not in parts[0] and ':' not in parts[0] and parts[0] != 'localhost':
                return 'docker.io/' + tag
            return tag

        roots = None
        if 'index.json' in members:
            index = members['index.json']
            require(index.isfile() and index.size <= 4 * 1024 * 1024, 'Invalid OCI root index')
            value = json.loads(stream.extractfile(index).read())
            require(isinstance(value, dict) and value.get('schemaVersion') == 2
                    and isinstance(value.get('manifests'), list) and len(value['manifests']) <= 128,
                    'Invalid OCI root index schema')
            roots = value['manifests']
        selected = {}
        for image in images:
            # docker save records repository tags, not registry manifest pins.
            tag = image.split('@', 1)[0]
            require(tag in found, 'Requested image is absent from Docker save archive')
            identities = [found[tag]['config']]
            if roots is not None:
                matching = []
                for root in roots:
                    require(isinstance(root, dict), 'Invalid OCI root descriptor')
                    annotations = root.get('annotations', {})
                    require(isinstance(annotations, dict), 'Invalid OCI image annotations')
                    name = annotations.get('io.containerd.image.name')
                    if name in (tag, canonical(tag)):
                        matching.append(root)
                require(len(matching) == 1, 'OCI root tag mapping is missing or ambiguous')
                closure(matching[0], found[tag])
                identities.append(matching[0]['digest'])
            selected[tag] = sorted(set(identities))
        return selected


def runtime_pins(report_path):
    report = load_json(report_path, 16 * 1024 * 1024)
    require(isinstance(report, dict) and report.get('exit_code') == 0
            and report.get('elf64_x86_64') is True and report.get('target') == 'StandaloneLinux64'
            and report.get('subtarget') == 'Server', 'Expected a successful reviewed Linux server build report')
    pins = {'nebula_build_report_sha256': sha256(report_path),
            'nebula_server_sha256': report.get('executable_sha256'),
            'nebula_managed_sha256': report.get('managed_assembly_sha256')}
    require(all(isinstance(value, str) and HEX.fullmatch(value) for value in pins.values()),
            'Invalid runtime hash pins')
    return pins


def preview_validator(root):
    path = regular(Path(root) / 'deployment/ansible/files/install-catalog-previews.py')
    spec = importlib.util.spec_from_file_location('catalog_preview_installer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(output, archive, report, server_image, panel_image, catalog_preview_pack=None):
    output, archive, report = Path(output).absolute(), regular(archive), regular(report)
    require(not output.exists() and not output.is_symlink(), 'Release output must be a new directory')
    for parent in output.parents:
        require(not parent.is_symlink(), 'Linked release output parent refused')
    pins = runtime_pins(report)
    ids = image_ids(archive, [server_image, panel_image, NGINX])
    if catalog_preview_pack is not None:
        catalog_preview_pack = regular(catalog_preview_pack)
        preview_validator(ROOT).validate(catalog_preview_pack, sha256(catalog_preview_pack))
    files = list(PAYLOAD)
    for path in sorted((ROOT / 'deployment/ansible').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
            files.append(path.relative_to(ROOT).as_posix())
    for name in files:
        regular(ROOT / name)
    output.mkdir(parents=True, mode=0o700)
    for name in files:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    shutil.copyfile(archive, output / 'images.tar')
    shutil.copyfile(report, output / 'runtime-report.json')
    files += ['images.tar', 'runtime-report.json']
    if catalog_preview_pack is not None:
        shutil.copyfile(catalog_preview_pack, output / 'catalog-previews.tar')
        files.append('catalog-previews.tar')
    manifest = {'format': 'nebula-linux-release-v1',
                'images': {'server': server_image, 'panel': panel_image}, 'image_ids': ids,
                'runtime_pins': pins,
                'files': {name: {'sha256': sha256(output / name), 'bytes': (output / name).stat().st_size}
                          for name in sorted(files)}}
    (output / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    verify(output)
    return {'release_prepared': True, 'files': len(files), 'manifest_sha256': sha256(output / 'release.json')}


def verify(release):
    release = Path(release).absolute()
    manifest = load_json(release / 'release.json')
    require(isinstance(manifest, dict) and set(manifest) == {'format', 'images', 'image_ids', 'runtime_pins', 'files'}
            and manifest['format'] == 'nebula-linux-release-v1', 'Unknown release manifest schema')
    files = manifest['files']
    require(isinstance(files, dict) and 8 <= len(files) <= 256, 'Invalid release inventory')
    for name, entry in files.items():
        safe_name(name)
        require(isinstance(entry, dict) and set(entry) == {'sha256', 'bytes'}
                and isinstance(entry['sha256'], str) and HEX.fullmatch(entry['sha256'])
                and type(entry['bytes']) is int and entry['bytes'] >= 0, 'Invalid release file pin')
        path = regular(release / name)
        require(path.stat().st_size == entry['bytes'] and sha256(path) == entry['sha256'],
                'Release file hash/size mismatch')
    required = set(PAYLOAD) | {'deployment/ansible/site.yaml', 'images.tar', 'runtime-report.json'}
    require(required <= files.keys(), 'Release inventory misses required installer inputs')
    require(all(name in required or name == 'catalog-previews.tar'
                or name.startswith('deployment/ansible/') for name in files),
            'Release contains an unsupported member')
    actual = {path.relative_to(release).as_posix() for path in release.rglob('*') if path.is_file()}
    require(actual == set(files) | {'release.json'}, 'Release contains unexpected files')
    require(isinstance(manifest['images'], dict) and set(manifest['images']) == {'server', 'panel'}
            and all(isinstance(value, str) and IMAGE.fullmatch(value) for value in manifest['images'].values()),
            'Invalid release image selection')
    require(runtime_pins(release / 'runtime-report.json') == manifest['runtime_pins'], 'Runtime pins differ')
    expected = image_ids(release / 'images.tar', [*manifest['images'].values(), NGINX])
    require(expected == manifest['image_ids'], 'Image identities differ')
    if 'catalog-previews.tar' in files:
        preview_validator(release).validate(release / 'catalog-previews.tar',
                                            files['catalog-previews.tar']['sha256'])
    return manifest


def install(release, address, tls_mode, public_enrollment=False):
    address = str(ipaddress.IPv4Address(address))
    require(tls_mode in ('public_acme', 'private_ca'), 'Unknown TLS mode')
    if tls_mode == 'public_acme':
        require(ipaddress.IPv4Address(address).is_global, 'Public TLS needs a globally routable IPv4 address')
    release = Path(release).absolute()
    manifest = verify(release)  # Complete input verification precedes package/service changes.
    require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64') and os.geteuid() == 0,
            'Install requires root on Ubuntu x86_64')
    os_release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            os_release[key] = value.strip('"')
    require(os_release.get('ID') == 'ubuntu' and re.fullmatch(r'\d+\.\d+', os_release.get('VERSION_ID', '')),
            'Install requires Ubuntu 26.04 or newer')
    require(tuple(map(int, os_release['VERSION_ID'].split('.'))) >= (26, 4), 'Ubuntu version is too old')
    os.umask(0o077)
    state = Path('/var/lib/nebula-preserved-installer')
    require(not state.is_symlink(), 'Linked installer state refused')
    state.mkdir(mode=0o700, exist_ok=True)
    os.chmod(state, 0o700)
    import fcntl
    lock_path = state / 'install.lock'
    require(not lock_path.is_symlink(), 'Linked installer lock refused')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.which('ansible-playbook') is None:
            subprocess.run(['apt-get', 'update'], check=True)
            subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', 'ansible-core'],
                           check=True, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
        inventory = {'all': {'children': {'nebula': {'hosts': {'localhost': {
            'ansible_connection': 'local', 'ansible_python_interpreter': '/usr/bin/python3'}}}}}}
        values = {**manifest['runtime_pins'], 'nebula_public_ip': address,
                  'nebula_image_archive': str(release / 'images.tar'),
                  'nebula_image_archive_sha256': manifest['files']['images.tar']['sha256'],
                  'nebula_server_image': manifest['images']['server'],
                  'nebula_panel_image': manifest['images']['panel'],
                  'nebula_expected_image_ids': manifest['image_ids'],
                  'nebula_max_processes': 2, 'nebula_tls_mode': tls_mode,
                  'nebula_public_enrollment': bool(public_enrollment),
                  'nebula_verify_reboot': False}
        if 'catalog-previews.tar' in manifest['files']:
            values.update(nebula_catalog_preview_archive=str(release / 'catalog-previews.tar'),
                          nebula_catalog_preview_archive_sha256=manifest['files']['catalog-previews.tar']['sha256'])
        for name, value in [('inventory.json', inventory), ('vars.json', values)]:
            path = state / name
            require(not path.is_symlink(), 'Linked installer settings refused')
            path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
            os.chmod(path, 0o600)
        command = ['ansible-playbook', '-i', str(state / 'inventory.json'), 'site.yaml',
                   '-e', '@' + str(state / 'vars.json')]
        environment = {**os.environ, 'ANSIBLE_CONFIG': str(release / 'deployment/ansible/ansible.cfg'),
                       'ANSIBLE_NOCOLOR': '1', 'ANSIBLE_LOCAL_TEMP': str(state / 'ansible-tmp')}
        subprocess.run(command + ['--syntax-check'], cwd=release / 'deployment/ansible',
                       env=environment, check=True)
        subprocess.run(command, cwd=release / 'deployment/ansible', env=environment, check=True)
    return {'deployment_checks_passed': True, 'tls_mode': tls_mode,
            'owner_login_file': '/opt/nebula-preserved/operator/panel-login.txt',
            'gameplay_acceptance': 'separate native-client verification required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='command', required=True)
    prepare_parser = modes.add_parser('prepare', help='Create portable release from reviewed local artifacts')
    prepare_parser.add_argument('--output', type=Path, required=True)
    prepare_parser.add_argument('--archive', type=Path, required=True)
    prepare_parser.add_argument('--runtime-report', type=Path, required=True)
    prepare_parser.add_argument('--server-image', required=True)
    prepare_parser.add_argument('--panel-image', required=True)
    prepare_parser.add_argument('--catalog-preview-pack', type=Path,
                                help='Optional private, validated flat preview tar (never needed for game play)')
    check_parser = modes.add_parser('verify', help='Read-only check of every release input')
    check_parser.add_argument('--release', type=Path, default=ROOT)
    install_parser = modes.add_parser('install', help='Autonomously install on this Ubuntu host')
    install_parser.add_argument('--release', type=Path, default=ROOT)
    install_parser.add_argument('--public-ip', required=True)
    install_parser.add_argument('--tls-mode', choices=('public_acme', 'private_ca'), default='public_acme')
    install_parser.add_argument('--public-enrollment', action='store_true',
                                help='Opt in to automatic preservation registration; does not verify Steam ownership')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.output, args.archive, args.runtime_report, args.server_image, args.panel_image,
                             args.catalog_preview_pack)
        elif args.command == 'verify':
            result = {'release_verified': bool(verify(args.release))}
        else:
            result = install(args.release, args.public_ip, args.tls_mode, args.public_enrollment)
        print(json.dumps(result))
    except (ValueError, OSError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Deployment stopped: {exc}\n')


if __name__ == '__main__':
    main()
