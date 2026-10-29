"""Explicit IPv4 HTTP adapter. Do not launch during static reconstruction."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

from aiohttp import web

from allocation import ipv4_address, network_port, validation_profile
from interaction_registry import InteractionRegistryPublisher
from public_access import AccessAuthority, AccessDenied, actor_scope
from service import Service
from state import Catalog, Store
from test_identity import private_concrete_ipv4
from wire import ProtocolError, decrypt, encrypt

ROOT = Path(__file__).resolve().parents[1]


class Backend:
    def __init__(self, state_dir, *, bind="127.0.0.1", advertise_ip="127.0.0.1", port=8080,
                 core_test_profile=None, managed_instances=False, local_test_identities=False,
                 public_access=False):
        if type(local_test_identities) is not bool:
            raise TypeError("local_test_identities must be a Boolean")
        self.bind_address = ipv4_address(bind, wildcard=True)
        self.advertised_ip = ipv4_address(advertise_ip)
        self.port = network_port(port)
        self.core_test_profile = validation_profile(core_test_profile)
        self.managed_instances = bool(managed_instances)
        self.local_test_identities = local_test_identities
        if type(public_access) is not bool:
            raise TypeError("public_access must be a Boolean")
        self.public_access = public_access
        if self.public_access and self.local_test_identities:
            raise ValueError("Public access and local test identities are mutually exclusive")
        if self.public_access and self.bind_address != "127.0.0.1":
            raise ValueError("Public access HTTP must bind loopback behind the reviewed TLS proxy")
        if self.local_test_identities and not (private_concrete_ipv4(self.bind_address)
                                               and private_concrete_ipv4(self.advertised_ip)):
            raise ValueError("Local test identities require concrete loopback or RFC1918 endpoints")
        if self.managed_instances and self.core_test_profile != "nonmini-semantic-v1":
            raise ValueError("Managed instances require --core-test-profile nonmini-semantic-v1")
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = state_dir
        self.store = Store(state_dir / "preservation.sqlite3",
                           local_test_identities=self.local_test_identities)
        self.access = AccessAuthority(self.store.db) if self.public_access else None
        self.service = Service(self.store, Catalog(ROOT / "protocol"),
                               core_test_profile=self.core_test_profile,
                               managed_instances=self.managed_instances)
        self.service.instances.advertised_ip = self.advertised_ip
        self.service.instances.core_test_profile = self.core_test_profile
        self.interactions = InteractionRegistryPublisher(self.store, ROOT / "protocol")
        self.log = (state_dir / "requests.jsonl").open("a", encoding="utf-8")
        self.maintenance_task = None

    def record(self, **event):
        self.log.write(json.dumps({"time": time.time(), **event}, ensure_ascii=True) + "\n")
        self.log.flush()

    def publish_state(self):
        """Refresh local inter-process state even while no HTTP request arrives."""
        self.service.notifications.import_acknowledgements(self.state_dir)
        self.store.export_instance_accounts(self.state_dir)
        self.service.housing.export_bindings(self.state_dir)
        self.interactions.export(self.state_dir)
        self.service.notifications.export(self.state_dir)
        if self.service.lifecycle:
            self.service.lifecycle.export_desired(self.state_dir)

    async def maintain_state(self):
        while True:
            await asyncio.sleep(2)
            try:
                self.publish_state()
            except Exception as exc:
                # Keep a transient file/import failure from permanently
                # stopping later refreshes; do not log identity contents.
                self.record(error="state_refresh_failed", error_type=type(exc).__name__)

    async def start_maintenance(self, _app):
        self.publish_state()
        self.maintenance_task = asyncio.create_task(self.maintain_state())

    async def handle(self, request):
        command = request.path.lstrip("/")
        if command == "preservation/health":
            return web.json_response({"service": "nebula-preservation",
                                      "reconstructed_http_handlers": sorted(self.service.ROUTES),
                                      "managed_instances": self.managed_instances,
                                      "local_test_identities": self.local_test_identities,
                                      "public_access": self.public_access,
                                      "game_ready": False,
                                      "networking_parity": "unproven"})
        if request.method != "GET" or "data" not in request.query:
            return web.Response(status=400, text="Expected encrypted GET request")
        try:
            plaintext = decrypt(request.query["data"])
        except (ValueError, UnicodeError):
            self.record(command=command, error="invalid_encrypted_request")
            return web.Response(status=400, text="Invalid encrypted request")
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        try:
            if self.access is None:
                response = self.service.dispatch(command, plaintext)
                self.publish_state()
            else:
                account = self.access.authenticate(request.headers.get("Authorization"))
                with actor_scope(account):
                    response = self.service.dispatch(command, plaintext)
                    self.publish_state()
        except AccessDenied as exc:
            self.record(command=command, request_sha256=digest, status=403,
                        error_type=type(exc).__name__)
            return web.Response(status=403, text=encrypt("ERROR"), content_type="text/plain")
        except ProtocolError as exc:
            self.record(command=command, request_sha256=digest, status=exc.status, error=str(exc))
            return web.Response(status=exc.status, text=encrypt("ERROR"), content_type="text/plain")
        self.record(command=command, request_sha256=digest, status=200,
                    response_bytes=len(response.encode("utf-8")))
        return web.Response(text=encrypt(response), content_type="text/plain")

    async def close(self, _app):
        if self.maintenance_task is not None:
            self.maintenance_task.cancel()
            try:
                await self.maintenance_task
            except asyncio.CancelledError:
                pass
            self.maintenance_task = None
        self.log.close()
        self.store.close()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind", default="127.0.0.1", help="HTTP listen IPv4; 0.0.0.0 listens on all IPv4 interfaces")
    p.add_argument("--advertise-ip", default="127.0.0.1", help="Exact concrete instance IPv4 admitted by the same-host allocator")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--core-test-profile", choices=["nexus-core-v1", "nonmini-core-v1", "nonmini-semantic-v1"],
                   help="Opt into a matching reviewed integration scope; nonmini also requires explicit personal-space bindings. Parity remains unproven")
    p.add_argument("--managed-instances", action="store_true",
                   help="Publish backend-owned desired instance state; requires nonmini-semantic-v1")
    p.add_argument("--local-test-identities", action="store_true",
                   help="Admit only the two fixed preservation test identities on concrete private endpoints")
    p.add_argument("--public-access", action="store_true",
                   help="Require per-account credentials; bind loopback behind TLS")
    p.add_argument("--state-dir", type=Path, default=Path("work/server-state"))
    p.add_argument("--listen", action="store_true", help="Explicitly enable future runtime validation")
    a = p.parse_args(argv)
    try:
        a.bind = ipv4_address(a.bind, wildcard=True)
        a.advertise_ip = ipv4_address(a.advertise_ip)
        a.port = network_port(a.port)
    except ValueError as exc:
        p.error(str(exc))
    if a.managed_instances and a.core_test_profile != "nonmini-semantic-v1":
        p.error("--managed-instances requires --core-test-profile nonmini-semantic-v1")
    if a.local_test_identities and not (private_concrete_ipv4(a.bind)
                                        and private_concrete_ipv4(a.advertise_ip)):
        p.error("--local-test-identities requires concrete loopback or RFC1918 bind and advertise addresses")
    if a.public_access and a.local_test_identities:
        p.error("--public-access cannot be combined with --local-test-identities")
    if a.public_access and a.bind != "127.0.0.1":
        p.error("--public-access requires --bind 127.0.0.1 behind TLS")
    return a


def main():
    a = parse_args()
    if not a.listen:
        print("Runtime validation is deferred. No listener started; --listen is required.", file=sys.stderr)
        raise SystemExit(2)
    backend = Backend(a.state_dir, bind=a.bind, advertise_ip=a.advertise_ip, port=a.port,
                      core_test_profile=a.core_test_profile, managed_instances=a.managed_instances,
                      local_test_identities=a.local_test_identities,
                      public_access=a.public_access)
    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_route("*", "/{path:.*}", backend.handle)
    app.on_startup.append(backend.start_maintenance)
    app.on_cleanup.append(backend.close)
    web.run_app(app, host=backend.bind_address, port=backend.port, access_log=None)


if __name__ == "__main__":
    main()
