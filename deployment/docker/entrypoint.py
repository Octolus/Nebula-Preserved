"""Linux container lifecycle; no import-time process, listener, or DB access."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen

SCENES = ('Nexus LeafPark Beach Cinema Home Greenhouse Waterfall StarCrawlers '
          'BlueWaveHideout DressingRoom CutteridgeEstate TheMoonlightRoom LeChalet '
          'LakeApartment SereneGarden WoodlandClearing TheNebulian SorcerersEyrie1 '
          'ZeroDistrictDen CampSilverLake FlyingDevice Deadquarters HollyridgeEstate '
          'WinterSnowGlobe TokyoApartment NebuHouse WestValleyApartment '
          'WhisperingHillsMansion CliffApartment TheCrypt ForgottenStation '
          'GreekSummerHouse MountainHideout GingerbreadHouse WindMillFarmHouse').split()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): value.update(chunk)
    return value.hexdigest()


def plan(env, root=Path('/opt/nebula'), runtime=Path('/opt/nebula-runtime'), state=Path('/var/lib/nebula')):
    mode = env.get('NEBULA_MODE', 'private')
    if mode not in {'private', 'public'} or env.get('COMPOSE_PROFILES', mode) != mode:
        raise ValueError('Select exactly matching private or public mode and Compose profile')
    advertise = str(ipaddress.IPv4Address(env.get('NEBULA_ADVERTISE_IP', '127.0.0.1')))
    if advertise == '0.0.0.0' or (mode == 'public' and advertise != '127.0.0.1'):
        raise ValueError('Public gateway requires internal loopback descriptor addresses')
    pins = [env.get(key, '') for key in ('NEBULA_BUILD_REPORT_SHA256', 'NEBULA_SERVER_SHA256', 'NEBULA_MANAGED_SHA256')]
    if any(not re.fullmatch('[0-9a-f]{64}', pin) for pin in pins):
        raise ValueError('All three reviewed build pins must be lowercase SHA-256')
    maximum = int(env.get('NEBULA_MAX_PROCESSES', '16'))
    idle = float(env.get('NEBULA_IDLE_TTL', '60'))
    if not 1 <= maximum <= 32 or not 0 <= idle <= 86400:
        raise ValueError('Process limit must be 1..32 and idle TTL 0..86400')
    backend = [sys.executable, str(root/'backend/server.py'), '--listen', '--bind', '127.0.0.1',
               '--advertise-ip', advertise, '--port', '8080', '--managed-instances',
               '--core-test-profile', 'nonmini-semantic-v1', '--state-dir', str(state)]
    catalog_policy = env.get('NEBULA_CATALOG_POLICY', 'preservation-catalog-v1')
    if catalog_policy not in {'none', 'preservation-catalog-v1'}:
        raise ValueError('Unknown preservation catalog policy')
    backend.extend(('--catalog-policy', catalog_policy))
    if mode == 'public': backend.append('--public-access')
    supervisor = [sys.executable, str(root/'tools/instance_supervisor.py'), '--run', '--state-dir', str(state),
                  '--binary', str(runtime/'build/NebulaServer.x86_64'), '--build-report', str(runtime/'build-linux-validation.json'),
                  '--build-report-sha256', pins[0], '--binary-sha256', pins[1], '--managed-assembly-sha256', pins[2],
                  '--bind', '127.0.0.1' if mode == 'public' else '0.0.0.0', '--advertise-ip', advertise,
                  '--port-range', '28000-28031', '--max-processes', str(maximum), '--idle-ttl', str(idle),
                  '--stop-grace', '15', '--allowed-profile', 'nonmini-semantic-v1']
    for scene in SCENES: supervisor.extend(('--allowed-scene', scene))
    config = SimpleNamespace(binary=runtime/'build/NebulaServer.x86_64', build_report=runtime/'build-linux-validation.json',
                             build_report_sha256=pins[0], binary_sha256=pins[1], managed_assembly_sha256=pins[2])
    return backend, supervisor, config


def preflight(env, root, runtime, config):
    if sys.platform != 'linux' or os.uname().machine not in {'x86_64', 'amd64'}:
        raise ValueError('The supplied Unity runtime requires Linux x86_64')
    sys.path.insert(0, str(root/'tools'))
    from instance_supervisor import validate_build
    validate_build(config)  # Reuse exact final supervisor admission; no alternate ELF policy.
    report = json.loads(config.build_report.read_text(encoding='utf-8'))
    artifacts = report.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('Complete Linux build artifact inventory required')
    seen = set()
    for row in artifacts:
        name = row.get('path') if isinstance(row, dict) else None
        if not isinstance(name, str): raise ValueError('Malformed runtime artifact inventory')
        relative = PurePosixPath(name)
        if relative.is_absolute() or '\\' in name or '..' in relative.parts or name in seen:
            raise ValueError('Unsafe or duplicate runtime artifact path')
        seen.add(name)
        target = (runtime/'build'/name).resolve(strict=True)
        if not target.is_relative_to((runtime/'build').resolve()) or not target.is_file():
            raise ValueError('Runtime artifact escapes the complete build directory')
        if target.stat().st_size != row.get('size') or digest(target) != row.get('sha256'):
            raise ValueError('Runtime artifact differs from the reviewed report')
    for key in ('NEBULA_ADMIN_TOKEN_FILE', 'NEBULA_ADMIN_OPERATORS_FILE'):
        secret = Path(env.get(key, ''))
        if not secret.is_file() or not 1 <= secret.stat().st_size <= 65536:
            raise ValueError('Explicit file-mounted management secrets are required')
    if len(Path(env['NEBULA_ADMIN_TOKEN_FILE']).read_text(encoding='utf-8').strip()) < 32:
        raise ValueError('Management token must contain at least 32 characters')


def backend_healthy():
    try:
        with urlopen('http://127.0.0.1:8080/preservation/health', timeout=2) as response:
            body = json.load(response)
            return response.status == 200 and body.get('service') == 'nebula-preservation' and body.get('managed_instances') is True
    except (OSError, ValueError): return False


class ServiceFailure(RuntimeError):
    """Only this lifetime's exact cleanup evidence can permit a backend retry."""
    def __init__(self, reason, *, retry_safe=False, healthy_seconds=0):
        super().__init__(reason)
        self.retry_safe = retry_safe
        self.healthy_seconds = healthy_seconds


def stop_owned(child, timeout):
    # Popen authority exists only in this attempt. Never load PIDs from disk.
    proof = dict(was_running=False, term_sent=False, forced=False, reaped=True, exit_code=None)
    if child is None: return proof
    try:
        proof['was_running'] = child.poll() is None
        if proof['was_running']:
            try:
                child.terminate()
                proof['term_sent'] = True
            except ProcessLookupError:
                pass
        try:
            proof['exit_code'] = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proof['forced'] = True
            child.kill()
            proof['exit_code'] = child.wait(timeout=3)
        proof['reaped'] = child.poll() is not None
    except Exception:
        # Unknown cleanup failures are not evidence of a completed lifetime.
        proof['reaped'] = False
    return proof


def supervise(backend, supervisor, stop, *, spawn=subprocess.Popen, healthy=backend_healthy,
              clock=time.monotonic, pause=time.sleep):
    if stop.is_set(): return 0
    owned_backend = owned_supervisor = None
    failed = None
    healthy_since = None
    failed_at = None
    try:
        owned_backend = spawn(backend, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        deadline = clock() + 30
        while not stop.is_set() and owned_backend.poll() is None and not healthy():
            if clock() >= deadline: raise RuntimeError('Backend startup health timed out')
            pause(0.2)
        if not stop.is_set():
            if owned_backend.poll() is not None: raise RuntimeError('Backend stopped during startup')
            healthy_since = clock()
            owned_supervisor = spawn(supervisor, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            while not stop.wait(0.25):
                # Supervisor failure wins a simultaneous failure: its worlds may
                # have escaped its lifetime. Never start another authority then.
                if owned_supervisor.poll() is not None:
                    failed = 'supervisor'
                    failed_at = clock()
                    break
                if owned_backend.poll() is not None:
                    failed = 'backend'
                    failed_at = clock()
                    break
    except Exception:
        # A lifetime boundary contains unexpected adapter/OS errors as unsafe.
        failed = 'startup'
    finally:
        supervisor_proof = stop_owned(owned_supervisor, 20)
        backend_proof = stop_owned(owned_backend, 10)
    if stop.is_set(): return 0
    safe = (failed == 'backend' and supervisor_proof['was_running']
            and supervisor_proof['term_sent'] and supervisor_proof['exit_code'] == 0
            and not supervisor_proof['forced'] and supervisor_proof['reaped']
            and backend_proof['reaped'])
    # The paired supervisor shutdown contract waits/reaps every owned world
    # before returning zero. A kill/timeout/nonzero outcome cannot prove this.
    raise ServiceFailure('Owned service failure: ' + str(failed), retry_safe=safe,
                         healthy_seconds=0 if healthy_since is None or failed_at is None else failed_at - healthy_since)


def run_service(backend, supervisor, stop, *, attempt=supervise, log=print):
    retries = 0
    while not stop.is_set():
        try:
            return attempt(backend, supervisor, stop)
        except ServiceFailure as failure:
            if failure.healthy_seconds >= 60: retries = 0
            if failure.retry_safe and retries < 3:
                delay = 2 ** retries
                retries += 1
                log('Backend exited; owned world cleanup confirmed; retry ' + str(retries)
                    + ' in ' + str(delay) + ' seconds', flush=True)
                if not stop.wait(delay): continue
                return 0
            # Preserve this network namespace while unhealthy. Unknown orphans
            # cannot be adopted or signalled from persisted journals. Full-stack
            # stop/recreation gives Docker authority over that container cgroup.
            log('Unsafe or repeated service failure; parked unhealthy; stop and recreate the full stack', flush=True)
            stop.wait()
            return 0
    return 0


def main():
    env = os.environ
    stop = threading.Event()
    for event in (signal.SIGTERM, signal.SIGINT): signal.signal(event, lambda *_: stop.set())
    root, runtime, state = Path('/opt/nebula'), Path('/opt/nebula-runtime'), Path('/var/lib/nebula')
    stage = 'configuration'
    try:
        backend, supervisor, config = plan(env, root, runtime, state)
        stage = 'runtime-artifacts'
        preflight(env, root, runtime, config)
        state.mkdir(parents=True, exist_ok=True)
        Path(env.get('HOME', '/tmp/nebula-home')).mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError, RuntimeError) as error:
        code = type(error).__name__
        if code not in {'ValueError', 'FileNotFoundError', 'PermissionError', 'RuntimeError', 'OSError'}:
            code = 'admission-error'
        print('Container preflight failed: stage=' + stage + ' code=' + code
              + '; parked unhealthy; check configuration, build pins and file permissions, then recreate the full stack', flush=True)
        stop.wait()
        return 0
    return run_service(backend, supervisor, stop)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print('container startup/lifecycle refused: '+str(exc), file=sys.stderr)
        raise SystemExit(1)
