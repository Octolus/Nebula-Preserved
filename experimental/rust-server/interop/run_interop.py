"""Synthetic protocol acceptance test: actual Rust CLI and unchanged Python TLS gateway.

This needs no desktop, browser, native client, input injection, or unlocked session.
It never locks/unlocks the user's desktop. Native-client compatibility is unproven.
"""
import argparse
import asyncio
from contextlib import closing
import datetime as dt
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
def reference_root(explicit):
    required = ('backend/wire.py', 'backend/public_access.py', 'backend/allocation.py',
                'experimental/remote-transport/server/remote_gateway.py',
                'protocol/interaction-mapping-bridge.json')
    candidates = [explicit.resolve()] if explicit else [ROOT, *ROOT.parents, Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        if all((candidate / name).is_file() for name in required):
            return candidate
    raise SystemExit('Reference repository not found; pass --reference with its root directory')

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference', '--reference-root', type=Path,
                    help='Reference repository root; otherwise search script and working-directory parents')
parser.add_argument('--candidate', type=Path, required=True,
                    help='Compiled Rust nebula-preserved-server executable; never a game client')
parser.add_argument('--work-dir', type=Path, required=True,
                    help='Private writable directory for synthetic state, certificates and logs')
args = parser.parse_args()
SOURCE = reference_root(args.reference)
args.candidate = args.candidate.resolve()
if args.candidate.name not in ('nebula-preserved-server', 'nebula-preserved-server.exe') or not args.candidate.is_file():
    parser.error('--candidate must be the compiled Rust nebula-preserved-server executable')
args.work_dir = args.work_dir.resolve()
BACKEND = SOURCE / 'backend'
PROTOCOL = SOURCE / 'protocol'  # Exact location also used by backend/allocation.py.
GATEWAY = SOURCE / 'experimental/remote-transport/server/remote_gateway.py'
sys.path.insert(0, str(BACKEND))
from wire import encrypt, decrypt, session_guid
from public_access import AccessAuthority, migrate
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ACCOUNT = '76561190000000001'  # Synthetic grammar fixture, no ownership assertion.
USERNAME = 'SyntheticInterop'
PLATFORM = 'StandaloneWindows'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def protocol_hash():
    digest = hashlib.sha256()
    for path in sorted(p for p in PROTOCOL.rglob('*') if p.is_file()):
        digest.update(path.relative_to(PROTOCOL).as_posix().encode())
        digest.update(b'\0')
        digest.update(bytes.fromhex(sha(path)))
    return digest.hexdigest()

def available_ports():
    held = []
    try:
        for _ in range(3):
            s = socket.socket(); s.bind(('127.0.0.1', 0)); held.append(s)
        return [s.getsockname()[1] for s in held]
    finally:
        for s in held:
            s.close()

def certificates(directory):
    now = dt.datetime.now(dt.timezone.utc)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic Interop Test CA')])
    ca = (x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
        .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(root_key, hashes.SHA256()))
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic Loopback Gateway')]))
        .issuer_name(root_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256()))
    ca_path, leaf_path, key_path = [directory / name for name in ('ca.pem', 'gateway.pem', 'gateway-key.pem')]
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    leaf_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca_path, leaf_path, key_path

def mid(name):
    value = 23
    for unit in name.encode('utf-16-le')[::2]:  # Protocol names below are ASCII.
        value = (value * 31 + unit) & 0xffffffff
    return value & 0xffff

def empty(name):
    return struct.pack('<H', mid(name))

def application(text):
    ciphertext = encrypt(text).encode('ascii')
    return empty('NebulaMessage') + struct.pack('<H', len(ciphertext) + 1) + ciphertext

def frame(*messages):
    batch = struct.pack('<d', time.time()) + b''.join(messages)
    return struct.pack('>I', len(batch)) + batch

async def recv_message(reader):
    size, = struct.unpack('>I', await asyncio.wait_for(reader.readexactly(4), 6))
    assert 10 <= size <= 65536, 'invalid outbound Telepathy frame'
    batch = await asyncio.wait_for(reader.readexactly(size), 6)
    assert math.isfinite(struct.unpack_from('<d', batch)[0]), 'invalid outbound timestamp'
    return batch[8:]

def application_plain(message):
    kind, size = struct.unpack_from('<HH', message)
    assert kind == mid('NebulaMessage') and len(message) == size + 3, 'invalid application message'
    return decrypt(message[4:].decode('ascii'))

async def await_closed(reader):
    async def drain():
        while await reader.read(65536):
            pass
    try:
        await asyncio.wait_for(drain(), 7)
    except (ConnectionResetError, ssl.SSLError):
        pass

async def eventually(predicate, reason, seconds=25):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, sqlite3.Error):
            pass
        await asyncio.sleep(.15)
    raise AssertionError(reason)

def http(port, route, fields):
    query = urllib.parse.urlencode({'data': encrypt('#'.join([*fields, PLATFORM]))})
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{route}?{query}', timeout=6) as response:
        return decrypt(response.read().decode('ascii'))

def presence(state, instance, guid):
    path = state / 'instances' / instance / 'instance-presence.json'
    return any(p.get('guid') == guid for p in json.loads(path.read_text())['players'])

async def tls_open(context, port, hostname='127.0.0.1'):
    return await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port, ssl=context, server_hostname=hostname), 6)

async def gateway_connection(context, port, scene_port, credential):
    reader, writer = await tls_open(context, port)
    assert writer.get_extra_info('ssl_object').selected_alpn_protocol() == 'nebula-game/1', 'ALPN mismatch'
    raw = credential.encode('ascii'); assert len(raw) == 85, 'credential grammar mismatch'
    writer.write(struct.pack('>4sHH', b'NRT1', scene_port, len(raw)) + raw)
    await writer.drain()
    assert await asyncio.wait_for(reader.readexactly(4), 6) == b'OK01', 'gateway did not admit actor'
    return reader, writer

async def spawn(reader, writer, guid):
    writer.write(frame(empty('Mirror.ReadyMessage'), empty('Mirror.AddPlayerMessage')))
    await writer.drain()
    assert await recv_message(reader) == empty('Mirror.ObjectSpawnStartedMessage'), 'spawn begin mismatch'
    message = await recv_message(reader)
    assert struct.unpack_from('<H', message)[0] == mid('Mirror.SpawnMessage'), 'spawn ID mismatch'
    net_id, local, owner, scene = struct.unpack_from('<IBBQ', message, 2)
    assert net_id > 0 and local == owner == 1 and scene == 0, 'spawn ownership mismatch'
    assert message[16:32] == bytes.fromhex('7318048699b0e4ed687c67606e379683'), 'spawn asset GUID byte order mismatch'
    assert await recv_message(reader) == empty('Mirror.ObjectSpawnFinishedMessage'), 'spawn finish mismatch'
    assert application_plain(await recv_message(reader)) == '0', 'application startup mismatch'
    writer.write(frame(application(f'1#{net_id}#{guid}#{USERNAME}#1#{PLATFORM}')))
    await writer.drain()
    # These authenticated replies prove opcode 1 reached the managed Rust engine.
    replies = {application_plain(await recv_message(reader)), application_plain(await recv_message(reader))}
    assert replies == {f'17#{guid}#', f'15#{guid}#'}, 'identity announcement replies mismatch'
    return net_id

async def main(args):
    run_dir = args.work_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(run_dir)
    state = run_dir / 'state'
    http_port, scene_port, tls_port = available_ports()
    ca, certificate, key = certificates(run_dir)
    tracked = [GATEWAY, BACKEND / 'wire.py', BACKEND / 'public_access.py', BACKEND / 'allocation.py']
    source_hashes = {path.relative_to(SOURCE).as_posix(): sha(path) for path in tracked}
    original_protocol_hash = protocol_hash()
    report = {'scope': 'synthetic protocol acceptance only; native-client acceptance unproven',
        'desktop_dependency': False, 'desktop_lock_changed': False,
        'windows_gateway_signal_lifecycle_shim': sys.platform == 'win32',
        'source_sha256': source_hashes, 'public_protocol_tree_sha256': original_protocol_hash,
        'rust_binary_sha256': sha(args.candidate), 'test_ca_sha256': sha(ca), 'checks': [], 'result': 'failed'}
    processes, logs, writers = [], [], []
    stage = 'start Rust CLI'
    try:
        env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE'] = '1'
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        def start(command, name):
            log = (run_dir / (name + '.log')).open('wb'); logs.append(log)
            process = subprocess.Popen(command, cwd=run_dir, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **flags)
            processes.append((name, process)); return process
        rust = start([str(args.candidate), 'serve', '--bind', f'127.0.0.1:{http_port}', '--state-dir', str(state),
            '--protocol-dir', str(PROTOCOL), '--managed-instances', '--max-worlds', '1',
            '--first-scene-port', str(scene_port), '--last-scene-port', str(scene_port)], 'rust')
        def healthy():
            if rust.poll() is not None:
                raise RuntimeError('Rust CLI exited before health response')
            with urllib.request.urlopen(f'http://127.0.0.1:{http_port}/preservation/health', timeout=2) as response:
                value = json.load(response)
                assert value['public_access'] is False and value['game_ready'] is False
                return True
        await eventually(healthy, 'Rust HTTP health timeout')
        report['checks'].append('actual Rust CLI HTTP listener; public-access flag off')
        stage = 'encrypted HTTP synthetic bootstrap'
        assert http(http_port, 'N2UserExist', [USERNAME, 'v72', 'false', ACCOUNT, '1.25']).startswith(ACCOUNT + '#')
        request_hash = secrets.token_hex(32)
        assert http(http_port, 'ChannelGUIDServlet', [ACCOUNT, request_hash]) == 'true#'
        guid = session_guid(ACCOUNT, request_hash)
        assert http(http_port, 'GetIinitInfosNeededServlet', [guid, ACCOUNT]).startswith(guid + '#true#')
        assert http(http_port, 'N2LoadSpace', [guid, ACCOUNT, 'Login', '', '', '']) == f'{guid}#false#false'
        def allocated():
            parts = http(http_port, 'N2SpaceLoading', [guid, ACCOUNT]).split('#')
            return parts if len(parts) == 6 and parts[1] == 'true' else None
        allocation = await eventually(allocated, 'managed world allocation timeout')
        instance = allocation[2]
        assert allocation[3:] == ['Nexus', '127.0.0.1', str(scene_port)], 'bounded world allocation mismatch'
        report['checks'].append('encrypted HTTP bootstrap/session/login and managed single-port world allocation')
        stage = 'controlled operator credential fixture'
        with closing(sqlite3.connect(state / 'preservation.sqlite3', timeout=3)) as db:
            db.row_factory = sqlite3.Row; migrate(db)
            credential = AccessAuthority(db).issue(ACCOUNT)
        report['checks'].append('existing public-access migration and synthetic salted credential; raw credential retained only in memory')
        stage = 'start unchanged Python gateway CLI'
        gateway = start([sys.executable, '-B', str(ROOT / 'gateway_cli_windows.py'), str(GATEWAY), '--listen', '--bind', '127.0.0.1',
            '--port', str(tls_port), '--first-scene-port', str(scene_port), '--last-scene-port', str(scene_port),
            '--state-dir', str(state), '--certificate', str(certificate), '--private-key', str(key)], 'gateway')
        context = ssl.create_default_context(cafile=str(ca)); context.set_alpn_protocols(['nebula-game/1'])
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        deadline = time.monotonic() + 15
        while True:
            if gateway.poll() is not None:
                raise RuntimeError('gateway CLI exited before TLS listener')
            try:
                reader, writer = await gateway_connection(context, tls_port, scene_port, credential)
                writers.append(writer); break
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(.1)
        report['checks'].append('fresh CA-verified loopback IP SAN TLS, ALPN nebula-game/1, exact NRT1 85-byte credential, OK01')
        stage = 'reject incorrect TLS hostname'
        try:
            unexpected_reader, unexpected_writer = await tls_open(context, tls_port, 'invalid.example')
        except ssl.SSLCertVerificationError:
            pass
        else:
            unexpected_writer.close(); raise AssertionError('wrong TLS hostname accepted')
        report['checks'].append('incorrect TLS hostname rejected by certificate verification')
        stage = 'Telepathy spawn and current GUID opcode 1'
        await spawn(reader, writer, guid)
        await eventually(lambda: presence(state, instance, guid), 'authenticated presence missing')
        report['checks'].append('Ready/AddPlayer, source-layout spawn, exact opcode 1 current GUID, authenticated presence')
        stage = 'forged cross-GUID denial'
        forged = 'f' * 32 if guid != 'f' * 32 else 'e' * 32
        writer.write(frame(application(f'3#{forged}#{guid}#{PLATFORM}'))); await writer.drain()
        await await_closed(reader)
        await eventually(lambda: not presence(state, instance, guid), 'forged-actor connection retained presence')
        report['checks'].append('forged foreign GUID after valid binding rejected and upstream presence removed')
        stage = 'credential revocation teardown'
        reader2, writer2 = await gateway_connection(context, tls_port, scene_port, credential); writers.append(writer2)
        await spawn(reader2, writer2, guid)
        await eventually(lambda: presence(state, instance, guid), 'second authenticated presence missing')
        with closing(sqlite3.connect(state / 'preservation.sqlite3', timeout=3)) as db:
            db.row_factory = sqlite3.Row
            assert AccessAuthority(db).revoke(ACCOUNT)
        await await_closed(reader2)
        await eventually(lambda: not presence(state, instance, guid), 'revoked connection retained presence')
        report['checks'].append('live credential revocation tears down TLS/upstream within revalidation window and removes presence')
        stage = 'revoked credential rejects new admission'
        rejected_reader, rejected_writer = await tls_open(context, tls_port); writers.append(rejected_writer)
        raw = credential.encode('ascii')
        rejected_writer.write(struct.pack('>4sHH', b'NRT1', scene_port, len(raw)) + raw); await rejected_writer.drain()
        assert await asyncio.wait_for(rejected_reader.read(4), 6) == b'', 'revoked credential admitted'
        report['checks'].append('revoked credential denied for subsequent NRT1 admission')
        report['result'] = 'passed'
    except Exception as error:
        report['failure'] = {'stage': stage, 'type': type(error).__name__, 'diagnostic': 'details intentionally omitted from sanitized report'}
    finally:
        for writer in writers:
            writer.close()
        cleanup = []
        for name, process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            cleanup.append({'name': name, 'exited': process.poll() is not None})
        for log in logs:
            log.close()
        if key.exists():
            key.unlink()
        report['cleanup'] = {'owned_processes': cleanup, 'private_key_deleted': not key.exists()}
        report['sources_unchanged'] = all(sha(SOURCE / path) == digest for path, digest in source_hashes.items())
        report['public_protocol_unchanged'] = protocol_hash() == original_protocol_hash
        report['desktop_lock_independent_design'] = 'headless subprocess/network/file APIs only; desktop lock state not inspected or changed'
        report_path = run_dir / 'report.json'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'result': report['result'], 'checks_passed': len(report['checks']), 'report_file': 'report.json', 'failure': report.get('failure')}))
    return 0 if report['result'] == 'passed' else 1

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main(args)))
