"""Issue/renew public IP TLS without exposing the backend or rotating authority.

Certbot owns its private ACME tree. Only verified runtime certificate/key copies
are installed. Never accepts an invalid certificate or changes account state.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile

CERTBOT_IMAGE = ('certbot/certbot:v5.4.0@sha256:'
                 '1dc5b4a99cce916f154c706569baf062600d7dea13e0711e7d7e1461d6230e39')
ACME_SERVER = 'https://acme-v02.api.letsencrypt.org/directory'
CERT_NAME = 'nebula-public'
COMPOSE = ['docker', 'compose', '--env-file', 'runtime.env', '-f', 'compose.yaml',
           '-f', 'compose.public.yaml', '-f', 'compose.host.yaml']


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Linked or missing TLS file rejected')
    if path.stat().st_size > 1024 * 1024:
        raise RuntimeError('TLS file exceeds size limit')
    return path


def directory(path, mode=0o700):
    if path.is_symlink():
        raise RuntimeError('Linked ACME directory rejected')
    path.mkdir(exist_ok=True, mode=mode)
    if not path.is_dir():
        raise RuntimeError('Invalid ACME directory')
    os.chmod(path, mode)


def public_address(value):
    address = ipaddress.IPv4Address(value)
    if str(address) != value or not address.is_global:
        raise ValueError('Public ACME requires a canonical globally routable IPv4 address')
    return str(address)


def certbot_command(root, address, operation):
    if operation not in ('issue', 'renew', 'preflight'):
        raise ValueError('Unknown certificate operation')
    command = ['docker', 'run', '--rm', '--read-only', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true',
               '--mount', f'type=bind,src={root}/acme/config,dst=/etc/letsencrypt',
               '--mount', f'type=bind,src={root}/acme/webroot,dst=/var/www/acme',
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m,mode=1777',
               '--tmpfs', '/var/lib/letsencrypt:rw,nosuid,nodev,size=16m,mode=1777',
               '--tmpfs', '/var/log/letsencrypt:rw,nosuid,nodev,size=16m,mode=1777',
               CERTBOT_IMAGE]
    if operation in ('issue', 'preflight'):
        command += ['certonly', '--non-interactive', '--agree-tos',
                    '--register-unsafely-without-email', '--preferred-profile', 'shortlived',
                    '--webroot', '-w', '/var/www/acme', '--ip-address', address,
                    '--cert-name', CERT_NAME, '--key-type', 'ecdsa', '--server', ACME_SERVER,
                    '--keep-until-expiring']
        if operation == 'preflight':
            command[command.index(CERT_NAME)] = 'nebula-preflight'
            command[command.index(ACME_SERVER)] = 'https://acme-staging-v02.api.letsencrypt.org/directory'
            command.append('--dry-run')
    else:
        command += ['renew', '--non-interactive', '--cert-name', CERT_NAME,
                    '--no-random-sleep-on-renew']
    return command


def run(command, **kwargs):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs)


def resolve_acme_file(root, name):
    # Certbot's live files are intentional symlinks to versioned archive files.
    # Resolve only inside the fixed private lineage, never to unrelated files.
    source = root / 'acme/config/live' / CERT_NAME / name
    resolved = source.resolve(strict=True)
    archive = root / 'acme/config/archive' / CERT_NAME
    if not resolved.is_relative_to(archive.resolve(strict=True)):
        raise RuntimeError('ACME lineage escapes its fixed archive')
    return regular(resolved)


def validate_certificate(root, address):
    leaf = resolve_acme_file(root, 'cert.pem')
    chain = resolve_acme_file(root, 'chain.pem')
    fullchain = resolve_acme_file(root, 'fullchain.pem')
    key = resolve_acme_file(root, 'privkey.pem')
    run(['openssl', 'verify', '-purpose', 'sslserver', '-verify_ip', address,
         '-untrusted', str(chain), str(leaf)])
    # A renewed short-lived certificate must remain valid long enough to recover
    # from the next hourly check failing. Never install expired/near-expiry data.
    run(['openssl', 'x509', '-checkend', '86400', '-noout', '-in', str(leaf)])
    cert_public = run(['openssl', 'x509', '-in', str(leaf), '-pubkey', '-noout']).stdout
    key_public = run(['openssl', 'pkey', '-in', str(key), '-pubout']).stdout
    if cert_public != key_public:
        raise RuntimeError('Public certificate and private key do not match')
    # Compare the actual fullchain contents with its separately validated parts.
    if fullchain.read_bytes().strip() != (leaf.read_bytes().strip() + b'\n' + chain.read_bytes().strip()):
        raise RuntimeError('Public fullchain differs from validated certificate and chain')
    return fullchain.read_bytes(), key.read_bytes()


def install_pair(root, certificate, key):
    secrets = root / 'secrets'
    directory(secrets)
    values = [('fullchain.pem', certificate), ('server-key.pem', key)]
    changed = False
    for name, data in values:
        destination = secrets / name
        if destination.is_symlink():
            raise RuntimeError('Linked runtime TLS file rejected')
        if destination.exists():
            regular(destination)
            changed |= destination.read_bytes() != data
        else:
            changed = True
    if not changed:
        return False
    staged = []
    try:
        for name, data in values:
            fd, temporary = tempfile.mkstemp(prefix='.tls-', dir=secrets)
            path = Path(temporary)
            staged.append((path, secrets / name))
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(path, 0, 1000)
            os.chmod(path, 0o440)
        # Existing running containers keep their old bind-mount inodes until
        # all replacements are ready and only the TLS sidecars are recreated.
        for temporary, destination in staged:
            os.replace(temporary, destination)
        return True
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def manage(root, address, operation, refresh_runtime=True):
    address = public_address(address)
    if root != Path('/opt/nebula-preserved'):
        raise ValueError('Deployment root must be /opt/nebula-preserved')
    directory(root)
    directory(root / 'acme')
    directory(root / 'acme/config')
    directory(root / 'acme/webroot', 0o755)
    directory(root / 'acme/webroot/.well-known', 0o755)
    directory(root / 'acme/webroot/.well-known/acme-challenge', 0o755)
    import fcntl
    lockpath = root / 'acme/renew.lock'
    if lockpath.is_symlink():
        raise RuntimeError('Linked renewal lock rejected')
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run(certbot_command(root, address, operation))
        if operation == 'preflight':
            print(json.dumps({'public_tls_preflight': 'passed', 'production_identity_changed': False}))
            return
        certificate, key = validate_certificate(root, address)
        print(json.dumps(activate_pair(root, certificate, key, refresh_runtime)))


def activate_pair(root, certificate, key, refresh_runtime=True):
    changed = install_pair(root, certificate, key)
    marker = root / 'acme/runtime-certificate.sha256'
    if marker.is_symlink():
        raise RuntimeError('Linked certificate receipt rejected')
    fingerprint = hashlib.sha256(certificate).hexdigest()
    pending = not marker.exists() or marker.read_text().strip() != fingerprint
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'nebula-preserved'],
                            check=False, stdout=subprocess.DEVNULL).returncode == 0
    if pending and active and refresh_runtime:
        run(COMPOSE + ['up', '-d', '--no-build', '--no-deps', '--force-recreate',
                       '--wait', '--wait-timeout', '120',
                       'public-https', 'public-game', 'panel-https'], cwd=root)
    if (active and refresh_runtime) or not pending:
        marker.write_text(fingerprint + '\n')
        os.chmod(marker, 0o600)
    return {'public_tls': 'verified', 'runtime_files_changed': changed,
            'tls_sidecars_refreshed': pending and active and refresh_runtime}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('issue', 'renew', 'preflight'))
    parser.add_argument('--address', required=True)
    parser.add_argument('--defer-runtime-refresh', action='store_true',
                        help='Installer will refresh the complete stack after all inputs are checked')
    args = parser.parse_args()
    try:
        manage(Path('/opt/nebula-preserved'), args.address, args.operation,
               refresh_runtime=not args.defer_runtime_refresh)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        # Do not print command output that could contain private ACME material.
        parser.exit(1, f'Public TLS operation failed: {type(exc).__name__}; inspect the private service journal.\n')


if __name__ == '__main__':
    main()
