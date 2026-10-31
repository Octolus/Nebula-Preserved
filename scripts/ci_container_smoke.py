#!/usr/bin/env python3
"""Disposable Linux Docker smoke check of locally built server/panel images.

Requires a complete reviewed Unity runtime in the server image. This checks
packaging, HTTP/panel authentication, real managed Nexus startup and persistence;
it does not test the Windows client or claim complete gameplay compatibility.
Only this run's random Compose project and empty volume may be used or removed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

NODE_IMAGE = "node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c"
NGINX_IMAGE = "nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236"
PINS = ("NEBULA_BUILD_REPORT_SHA256", "NEBULA_SERVER_SHA256", "NEBULA_MANAGED_SHA256")
ORIGIN = "http://ci.nebula.invalid"
SERVICES = {"server", "private-http", "panel"}
LABEL = "nebula.ci.owner"

# Code runs only inside a one-shot container with this run's NEW empty volume.
SEED = r'''
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,"/opt/nebula/backend")
from server import Backend
from wire import session_guid
state=Path("/var/lib/nebula")
assert not any(state.iterdir()), "CI requires an empty new volume"
b=Backend(state,core_test_profile="nonmini-semantic-v1",managed_instances=True)
try:
    account="7656119"+"0000000001"
    b.store.account(account,"CIPlayerOne")
    b.store.account("7656119"+"0000000002","CIPlayerTwo")
    b.store.bind_session(account,session_guid(account,"0"*64))
    b.service.shop.set_wallet(account,117,20,0)
    b.publish_state()
finally:
    b.log.close();b.store.close()
print("CI synthetic state initialized")
'''

# A read-only SQLite connection observes seeded durable tables. The HTTP API is
# the sole live writer for demand/poll; no second Backend or Store is created.
PROBE = r'''
import sys,json,sqlite3,time,hashlib,os,re
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
sys.path.insert(0,"/opt/nebula/backend")
from wire import encrypt,decrypt
def expected_world_argv(row):
    assert re.fullmatch(r"pub-[0-9a-f]{32}",row["instance_id"])
    assert re.fullmatch(r"[0-9a-f]{32}",row["start_token"])
    assert re.fullmatch(r"[0-9a-f]{32}",row["lease_token"])
    assert row["psidglobal"]=="Nexus" and row["readiness_profile"]=="nonmini-semantic-v1"
    assert type(row["port"]) is int and 28000<=row["port"]<=28031
    log="/var/lib/nebula/supervisor-logs/"+row["instance_id"]+"/"+row["start_token"]+".unity.log"
    return ["/opt/nebula-runtime/build/NebulaServer.x86_64","-batchmode","-nographics","-logFile",log,
            "--nebula-instance","--nebula-state-dir","/var/lib/nebula","--nebula-instance-id",row["instance_id"],
            "--nebula-space","Nexus","--nebula-bind","0.0.0.0","--nebula-advertise-ip","127.0.0.1",
            "--nebula-port",str(row["port"]),"--nebula-board-tables","0","--nebula-darts-tables","0",
            "--nebula-pool-tables","0","--nebula-bowling-lanes","0",
            "--nebula-core-test-profile","nonmini-semantic-v1"]
state=Path("/var/lib/nebula")
db=sqlite3.connect("file:/var/lib/nebula/preservation.sqlite3?mode=ro",uri=True)
account="7656119"+"0000000001"
guid=db.execute("SELECT guid FROM sessions WHERE ps4_id=?",(account,)).fetchone()[0]
def call(route,fields):
    data=encrypt("#".join(fields+["StandaloneWindows"]))
    with urlopen("http://127.0.0.1:8080/"+route+"?"+urlencode({"data":data}),timeout=5) as response:
        return decrypt(response.read().decode())
assert call("N2LoadSpace",[guid,account,"Nexus","false","",""])==guid+"#false#false"
deadline=time.monotonic()+120
while True:
    parts=call("N2SpaceLoading",[guid,account]).split("#")
    if len(parts)==6 and parts[1]=="true":
        runtime=json.loads((state/"managed-instance-runtime.json").read_text())
        rows=[r for r in runtime["instances"] if r["instance_id"]==parts[2]]
        if len(rows)==1 and rows[0]["state"]=="healthy": break
    assert time.monotonic()<deadline,"Managed Nexus readiness timed out"
    time.sleep(1)
instance=parts[2]
row=rows[0];pid=row["pid"]
assert type(pid) is int and pid>1
exe=Path("/proc")/str(pid)/"exe"
assert os.path.samefile(exe,"/opt/nebula-runtime/build/NebulaServer.x86_64")
argv=(Path("/proc")/str(pid)/"cmdline").read_bytes().rstrip(b"\0").split(b"\0")
# The supervisor lease is not a Unity argument. Bind the exact original argv,
# including its per-attempt log token, current instance, port and scene instead.
assert row["instance_id"]==instance and row["port"]==int(parts[5])
assert argv==[value.encode() for value in expected_world_argv(row)], "Owned Unity argv differs from supervisor contract"
assert row["build_sha256"]==os.environ["NEBULA_SERVER_SHA256"]
# Every row/column of these durable fixture tables must survive restart exactly.
tables=("profiles","sessions","shop_wallets","profile_state")
snapshot={t:sorted(db.execute('SELECT * FROM "'+t+'"').fetchall(),key=repr) for t in tables}
assert db.execute("SELECT crystals,np FROM shop_wallets WHERE ps4_id=?",(account,)).fetchone()==(117,20)
db.close()
print(json.dumps({"world":"Nexus","owned_process":True,"durable_sha256":hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()}))
'''


class SmokeError(RuntimeError):
    pass


def runtime_pins(path):
    """Accept only the three build hashes, never arbitrary Compose variables."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in PINS or key in values or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise SmokeError("runtime.env must contain exactly the three reviewed lowercase build hashes")
        values[key] = value
    if set(values) != set(PINS):
        raise SmokeError("All three reviewed runtime hashes are required")
    return values


class Docker:
    def __init__(self, timeout=480):
        self.deadline = time.monotonic() + timeout

    def run(self, *args, stdin=None, timeout=60, allow_failure=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeError("CI smoke total deadline exceeded")
        try:
            environment = {k: v for k, v in os.environ.items() if not k.startswith(("NEBULA_", "COMPOSE_"))}
            result = subprocess.run(["docker", *args], input=stdin, text=True, capture_output=True, env=environment,
                                    timeout=min(timeout, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SmokeError("Docker command failed or timed out") from exc
        if result.returncode and not allow_failure:
            # Child output may contain operator secrets. Never echo it.
            raise SmokeError("Docker command failed (exit " + str(result.returncode) + ")")
        return result.stdout.strip() if not result.returncode else None

    def json(self, *args, **kwargs):
        return json.loads(self.run(*args, **kwargs))


def image_id(docker, reference):
    rows = docker.json("image", "inspect", reference)
    if len(rows) != 1 or rows[0].get("Os") != "linux" or rows[0].get("Architecture") != "amd64":
        raise SmokeError("A local Linux amd64 image is required")
    identity = rows[0].get("Id", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise SmokeError("Invalid local image identity")
    return identity


def private_config(config, project, server_image, panel_image, directory):
    """Keep production service lifecycle/security; replace only CI resources."""
    selected = {name: json.loads(json.dumps(config["services"][name])) for name in SERVICES}
    for name, service in selected.items():
        if service.get("privileged") or service.get("user") != "1000:1000" or not service.get("read_only"):
            raise SmokeError("Unexpected production container security contract")
        service.pop("build", None)
        service.pop("profiles", None)
        service.pop("container_name", None)
        service["restart"] = "no"
        if name in {"server", "panel"}:
            service["image"] = server_image if name == "server" else panel_image
            target = 8081 if name == "server" else 4321
            service["ports"] = [{"target": target, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}]
    selected["panel"]["environment"]["NEBULA_PANEL_ORIGIN"] = ORIGIN
    selected["private-http"]["image"] = NGINX_IMAGE
    if selected["private-http"].get("network_mode") != "service:server":
        raise SmokeError("Private proxy must share the server namespace")
    mounts = selected["server"].get("volumes", [])
    if len(mounts) != 1 or mounts[0].get("type") != "volume" or mounts[0].get("target") != "/var/lib/nebula":
        raise SmokeError("Server must use only the disposable state volume")
    mounts[0] = dict(mounts[0], source="state")
    secrets_config = {name: {"file": str(directory / "secrets" / filename)} for name, filename in
                      (("admin_token", "admin-token.txt"), ("admin_operators", "admin-operators.json"),
                       ("panel_session_key", "panel-session-key.txt"))}
    return {"name": project, "services": selected, "secrets": secrets_config,
            "volumes": {"state": {"name": project + "_state", "external": True}},
            "networks": config.get("networks", {})}


def response(url, *, data=None, headers=None):
    request = Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers or {})
    try:
        with urlopen(request, timeout=5) as result:
            return result.status, result.read(1024 * 1024), result.headers
    except HTTPError as error:
        return error.code, error.read(65536), error.headers


class Smoke:
    def __init__(self, docker, repository, directory, project):
        if not re.fullmatch(r"nebula-ci-[0-9a-f]{24}", project):
            raise SmokeError("Only a new random CI project is accepted")
        self.docker, self.repo, self.directory, self.project = docker, Path(repository), Path(directory), project
        self.volume = project + "_state"
        self.file = self.directory / "compose.json"
        self.created_volume = False
        self.started = False
        self.oneoffs = []

    def compose(self, *args, **kwargs):
        return self.docker.run("compose", "--project-name", self.project, "-f", str(self.file), *args, **kwargs)

    def create_volume(self):
        if self.docker.run("volume", "inspect", self.volume, allow_failure=True) is not None:
            raise SmokeError("Refusing an existing volume")
        self.created_volume = True
        self.docker.run("volume", "create", "--label", LABEL + "=" + self.project, self.volume)
        rows = self.docker.json("volume", "inspect", self.volume)
        if len(rows) != 1 or rows[0].get("Labels", {}).get(LABEL) != self.project:
            raise SmokeError("Volume ownership mismatch")

    def oneoff(self, name, image, args, *, mounts=(), stdin=None, user="1000:1000", timeout=90, capabilities=()):
        name = self.project + "-" + name
        if self.docker.run("container", "inspect", name, allow_failure=True) is not None:
            raise SmokeError("Refusing an existing helper container")
        self.oneoffs.append(name)
        command = ["run", "--rm", "--name", name, "--label", LABEL + "=" + self.project,
                   "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                   "--user", user, "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m,mode=1777"]
        for capability in capabilities:
            command.extend(("--cap-add", capability))
        for mount in mounts:
            command.extend(("--mount", mount))
        if stdin is not None:
            command.append("-i")
        command.extend(("--entrypoint", args[0], image, *args[1:]))
        return self.docker.run(*command, stdin=stdin, timeout=timeout)

    def containers(self):
        ids = self.docker.run("ps", "-aq", "--filter", "label=com.docker.compose.project=" + self.project).split()
        if not ids:
            return []
        rows = self.docker.json("container", "inspect", *ids)
        for row in rows:
            labels = row.get("Config", {}).get("Labels", {})
            if labels.get("com.docker.compose.project") != self.project or labels.get("com.docker.compose.service") not in SERVICES:
                raise SmokeError("Unknown container in disposable project; refusing adoption")
        return rows

    def start(self):
        self.started = True  # A failed/timeout 'up' can already have created children.
        self.compose("up", "--no-build", "--pull", "never", "--detach", "--wait", "--wait-timeout", "150", timeout=180)
        rows = self.containers()
        if len(rows) != 3:
            raise SmokeError("Expected exactly three private services")
        ports = {}
        for row in rows:
            name = row["Config"]["Labels"]["com.docker.compose.service"]
            bindings = row["HostConfig"].get("PortBindings") or {}
            expected = {"8081/tcp"} if name == "server" else {"4321/tcp"} if name == "panel" else set()
            if set(bindings) != expected or any(b["HostIp"] != "127.0.0.1" for values in bindings.values() for b in values):
                raise SmokeError("Raw scene or management port unexpectedly published")
            if expected:
                key = next(iter(expected))
                actual = row["NetworkSettings"]["Ports"][key]
                if len(actual) != 1 or actual[0]["HostIp"] != "127.0.0.1":
                    raise SmokeError("Expected one loopback port")
                ports[name] = "http://127.0.0.1:" + actual[0]["HostPort"]
        return ports

    def panel(self, urls, password):
        # A running SSR/nginx process can briefly precede HTTP readiness. The
        # fixed Host/Origin keeps application origin checks intact while Docker
        # chooses disposable loopback transport ports.
        for url, headers in ((urls["server"] + "/preservation/health", {}),
                             (urls["panel"] + "/login", {"Host": "ci.nebula.invalid"})):
            deadline = min(self.docker.deadline, time.monotonic() + 25)
            while True:
                try:
                    if response(url, headers=headers)[0] == 200:
                        break
                except (OSError, URLError):
                    pass
                if time.monotonic() >= deadline:
                    raise SmokeError("Container HTTP startup timed out")
                time.sleep(0.25)
        status, body, _ = response(urls["server"] + "/preservation/health")
        value = json.loads(body)
        if status != 200 or value.get("managed_instances") is not True or value.get("public_access") is not False:
            raise SmokeError("Private API health failed")
        if response(urls["server"] + "/management/v1/health")[0] == 200:
            raise SmokeError("Management leaked through the private proxy")
        for operator, pw in (("ci-owner", password), ("ci-moderator", self.mod_password)):
            headers = {"Host": "ci.nebula.invalid", "Origin": ORIGIN, "Content-Type": "application/json"}
            status, _, reply = response(urls["panel"] + "/api/login", data={"id": operator, "password": pw}, headers=headers)
            cookie = reply.get("Set-Cookie", "").split(";", 1)[0]
            if status != 200 or not cookie.startswith("nebula_panel="):
                raise SmokeError("Panel authentication failed")
            if response(urls["panel"] + "/api/manage/stats", headers={"Cookie": cookie, "Host": "ci.nebula.invalid"})[0] != 200:
                raise SmokeError("Panel cannot reach internal management")
        if response(urls["panel"] + "/api/login", data={"id": "ci-owner", "password": "invalid"}, headers=headers)[0] != 401:
            raise SmokeError("Invalid panel password was not refused")

    def world(self):
        result = self.compose("exec", "-T", "server", "python", "-c", PROBE, timeout=135)
        value = json.loads(result)
        if value.get("owned_process") is not True or value.get("world") != "Nexus" or not re.fullmatch(r"[0-9a-f]{64}", value.get("durable_sha256", "")):
            raise SmokeError("Invalid managed scene result")
        return value["durable_sha256"]

    def cleanup(self):
        # Allow bounded cleanup after the main deadline; never apply it to a
        # supplied project, supplied volume, or names without our exact labels.
        self.docker.deadline = max(self.docker.deadline, time.monotonic() + 100)
        for name in self.oneoffs:
            raw = self.docker.run("container", "inspect", name, allow_failure=True)
            if raw is not None:
                rows = json.loads(raw)
                if len(rows) != 1 or rows[0].get("Config", {}).get("Labels", {}).get(LABEL) != self.project:
                    raise SmokeError("Helper cleanup ownership mismatch")
                self.docker.run("container", "rm", "--force", rows[0]["Id"])
        if self.started:
            self.containers()  # Validate all project members before Compose cleanup.
            self.compose("down", "--timeout", "45", timeout=65)
            if self.containers():
                raise SmokeError("Disposable containers survived cleanup")
        if self.created_volume:
            raw = self.docker.run("volume", "inspect", self.volume, allow_failure=True)
            if raw is None:
                return
            rows = json.loads(raw)
            if len(rows) != 1 or rows[0].get("Labels", {}).get(LABEL) != self.project:
                raise SmokeError("Volume cleanup ownership mismatch")
            self.docker.run("volume", "rm", self.volume)


def execute(args, docker=None):
    if sys.platform != "linux":
        raise SmokeError("Run the container smoke check on Linux")
    docker = docker or Docker(args.timeout)
    repo = Path(__file__).resolve().parents[1]
    pins = runtime_pins(args.runtime_env)
    server, panel = image_id(docker, args.server_image), image_id(docker, args.panel_image)
    project = "nebula-ci-" + secrets.token_hex(12)
    with tempfile.TemporaryDirectory(prefix=project + "-") as temporary:
        directory = Path(temporary)
        os.chmod(directory, 0o700)
        secret_dir = directory / "secrets"
        secret_dir.mkdir(mode=0o700)
        env_file = directory / "compose.env"
        env_file.write_text("\n".join(k + "=" + v for k, v in pins.items()) + "\nNEBULA_MODE=private\nCOMPOSE_PROFILES=private\n", encoding="utf-8")
        # The CLI must not inherit an operator's .env or NEBULA_* settings.
        config = docker.json("compose", "--project-name", project, "--env-file", str(env_file),
                             "-f", str(repo / "deployment/docker/compose.yaml"), "--profile", "private", "config", "--format", "json")
        config = private_config(config, project, server, panel, directory)
        smoke = Smoke(docker, repo, directory, project)
        smoke.file.write_text(json.dumps(config), encoding="utf-8")
        password, smoke.mod_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        try:
            mounts = ("type=bind,src=" + str(repo / "admin-panel/scripts") + ",dst=/bootstrap,readonly",
                      "type=bind,src=" + str(secret_dir) + ",dst=/secrets")
            for name, pw, extra in (("ci-owner", password, []), ("ci-moderator", smoke.mod_password, ["--add-login"])):
                smoke.oneoff("bootstrap-" + name, NODE_IMAGE,
                             ["node", "/bootstrap/bootstrap.mjs", "--dir", "/secrets", "--owner", name, "--password-stdin", *extra],
                             mounts=mounts, stdin=pw + "\n", user=str(os.getuid()) + ":" + str(os.getgid()))
            # Secrets remain private inside the TEMP root and readable only by
            # service UID1000. Directory stays host-owned for reliable cleanup.
            smoke.oneoff("permissions", server, ["python", "-c", "import os,pathlib; p=pathlib.Path('/secrets'); os.chmod(p,0o755); [(os.chmod(f,0o400),os.chown(f,1000,1000)) for f in p.iterdir()]"],
                         mounts=(mounts[1],), user="0:0", capabilities=("CHOWN", "FOWNER"))
            smoke.create_volume()
            state_mount = "type=volume,src=" + smoke.volume + ",dst=/var/lib/nebula"
            smoke.oneoff("volume-permissions", server, ["python", "-c", "import os; os.chown('/var/lib/nebula',1000,1000)"], mounts=(state_mount,), user="0:0", capabilities=("CHOWN",))
            smoke.oneoff("seed", server, ["python", "-c", SEED], mounts=(state_mount,))
            if smoke.containers():
                raise SmokeError("Refusing an existing Compose project")
            docker.run("pull", NGINX_IMAGE, timeout=90)
            urls = smoke.start()
            smoke.panel(urls, password)
            before = smoke.world()
            smoke.compose("down", "--timeout", "45", timeout=65)
            urls = smoke.start()
            smoke.panel(urls, password)
            if smoke.world() != before:
                raise SmokeError("Durable synthetic state changed across restart")
        finally:
            smoke.cleanup()
    return {"result": "passed", "server_image": server, "panel_image": panel,
            "checks": ["private API", "owner/moderator login", "hidden management", "owned Nexus", "restart persistence", "owned cleanup"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-image", required=True, help="Local Linux amd64 server image; never pulled")
    parser.add_argument("--panel-image", required=True, help="Local Linux amd64 panel image; never pulled")
    parser.add_argument("--runtime-env", type=Path, required=True, help="Exactly the three reviewed build hash assignments")
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    if not 180 <= args.timeout <= 900:
        parser.error("--timeout must be between 180 and 900 seconds")
    try:
        print(json.dumps(execute(args), sort_keys=True))
    except (SmokeError, OSError, ValueError, URLError) as error:
        print("Container smoke failed: " + type(error).__name__ + "; secret-bearing child output suppressed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
