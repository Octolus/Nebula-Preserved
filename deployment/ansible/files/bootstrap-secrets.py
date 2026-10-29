"""First-install only: never overwrite credentials or the operator CA."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys


def bootstrap(root, address):
    ip = str(ipaddress.IPv4Address(address))
    private, secret = root / 'operator', root / 'secrets'
    os.umask(0o077)
    private.mkdir(exist_ok=True, mode=0o700)
    secret.mkdir(exist_ok=True, mode=0o700)
    for directory in (root, private, secret):
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError('Linked or invalid deployment directory')
    for directory in (private, secret):
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Non-regular secret rejected')

    def create(path, data):
        with path.open('x') as stream:
            stream.write(data)

    def run(*args):
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if not (secret / 'admin-operators.json').exists():
        # Refuse partial setup rather than silently rotating credentials.
        for path in (secret / 'admin-token.txt', secret / 'panel-session-key.txt', private / 'panel-login.txt'):
            if path.exists():
                raise RuntimeError('Partial secret setup; inspect private files before retrying')
        password, salt = secrets.token_urlsafe(24), secrets.token_hex(16)
        hashed = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32).hex()
        create(private / 'panel-login.txt', 'Username: owner\nPassword: ' + password + '\n')
        create(secret / 'admin-token.txt', secrets.token_urlsafe(48))
        create(secret / 'panel-session-key.txt', secrets.token_urlsafe(48))
        create(secret / 'admin-operators.json', json.dumps({'operators': [{
            'id': 'owner', 'role': 'owner', 'enabled': True,
            'password_scrypt': 'scrypt$16384$8$1$' + salt + '$' + hashed,
        }]}))
    for path in (secret / 'admin-token.txt', secret / 'panel-session-key.txt',
                 private / 'panel-login.txt', secret / 'admin-operators.json'):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('Incomplete operator credentials; inspect before retrying')
    account_key = private / 'account-operator.key'
    if not account_key.exists():
        with account_key.open('xb') as stream:
            stream.write(secrets.token_bytes(48))
    os.chown(account_key, 1000, 1000)
    os.chmod(account_key, 0o600)
    ca, key = private / 'ca.pem', private / 'ca-key.pem'
    cert, server_key = secret / 'fullchain.pem', secret / 'server-key.pem'
    if not ca.exists():
        if key.exists() or cert.exists() or server_key.exists():
            raise RuntimeError('Partial PKI setup; inspect before retrying')
        run('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes', '-days', '3650',
            '-subj', '/CN=Nebula Preservation Operator Root', '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', str(key), '-out', str(ca))
    if not cert.exists():
        if server_key.exists():
            raise RuntimeError('Partial server certificate setup')
        csr, ext = private / 'server.csr', private / 'server.ext'
        create(ext, 'subjectAltName=IP:' + ip + '\nbasicConstraints=critical,CA:FALSE\n'
               'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
        run('openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes', '-subj', '/CN=Nebula Preservation Server',
            '-keyout', str(server_key), '-out', str(csr))
        run('openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca), '-CAkey', str(key),
            '-CAcreateserial', '-days', '365', '-sha256', '-extfile', str(ext), '-out', str(cert))
        csr.unlink()
        ext.unlink()
    run('openssl', 'x509', '-in', str(ca), '-outform', 'DER', '-out', str(private / 'operator-ca.der'))
    run('openssl', 'verify', '-CAfile', str(ca), '-verify_ip', ip, str(cert))
    run('openssl', 'x509', '-checkend', '2592000', '-noout', '-in', str(cert))
    certificate_public = subprocess.check_output(['openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'])
    private_public = subprocess.check_output(['openssl', 'pkey', '-in', str(server_key), '-pubout'],
                                             stderr=subprocess.PIPE)
    if certificate_public != private_public:
        raise RuntimeError('Server certificate and private key do not match')
    for path in secret.iterdir():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Non-regular secret rejected')
        os.chown(path, 0, 1000)
        os.chmod(path, 0o440)
    print('Secrets and TLS verified; owner login remains root-only')


if __name__ == '__main__':
    bootstrap(Path('/opt/nebula-preserved'), sys.argv[1])
