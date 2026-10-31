"""Offline TEMP/fake-Docker regression checks; no daemon or listeners needed."""
import ast
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("ci_container_smoke", Path(__file__).with_name("ci_container_smoke.py"))
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
PROJECT = "nebula-ci-" + "a" * 24
IMAGE = "sha256:" + "b" * 64


def configuration():
    return {"services": {
        "server": {"image": "server:local", "user": "1000:1000", "read_only": True,
                   "build": {}, "restart": "unless-stopped", "environment": {},
                   "volumes": [{"type": "volume", "source": "state", "target": "/var/lib/nebula"}],
                   "ports": [{"target": 8090, "published": "8090"}]},
        "panel": {"image": "panel:local", "user": "1000:1000", "read_only": True,
                  "build": {}, "environment": {}, "profiles": ["private"]},
        "private-http": {"user": "1000:1000", "read_only": True, "network_mode": "service:server", "profiles": ["private"]},
        "public-game": {"privileged": True}}, "networks": {"default": {"name": PROJECT + "_default"}}}


class FakeDocker:
    def __init__(self, fail=None):
        self.deadline = 0
        self.calls, self.volumes, self.children, self.helpers = [], {}, {}, {}
        self.fail = fail
        self.up_count = self.exec_count = 0

    def json(self, *args, **kwargs):
        return json.loads(self.run(*args, **kwargs))

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": IMAGE, "Os": "linux", "Architecture": "amd64"}])
        if args[0] == "compose" and "config" in args:
            return json.dumps(configuration())
        if args[:2] == ("volume", "inspect"):
            return json.dumps([self.volumes[args[2]]]) if args[2] in self.volumes else None
        if args[:2] == ("volume", "create"):
            name = args[-1]
            project = args[3].split("=", 1)[1]
            self.volumes[name] = {"Name": name, "Labels": {smoke.LABEL: project}}
            if self.fail == "volume-create-after-write":
                raise smoke.SmokeError("timeout after create")
            return name
        if args[:2] == ("volume", "rm"):
            del self.volumes[args[2]]
            return "removed"
        if args[:2] == ("container", "inspect"):
            rows = [self.children.get(name, self.helpers.get(name)) for name in args[2:]]
            return json.dumps(rows) if all(rows) else None
        if args[:2] == ("container", "rm"):
            identity = args[-1]
            self.helpers = {k: v for k, v in self.helpers.items() if v["Id"] != identity}
            return identity
        if args[0] == "run":
            name = args[args.index("--name") + 1]
            label = args[args.index("--label") + 1].split("=", 1)[1]
            if self.fail == "helper-timeout":
                self.helpers[name] = {"Id": "c" * 64, "Config": {"Labels": {smoke.LABEL: label}}}
                raise smoke.SmokeError("helper timed out")
            if self.fail == "seed" and name.endswith("-seed"):
                raise smoke.SmokeError("seed failure")
            return "ok"
        if args[0] == "ps":
            return "\n".join(self.children)
        if args[0] == "pull":
            return "pulled immutable image"
        if args[0] == "compose":
            project = args[args.index("--project-name") + 1]
            if "up" in args:
                self.up_count += 1
                for index, name in enumerate(sorted(smoke.SERVICES)):
                    target = "8081/tcp" if name == "server" else "4321/tcp" if name == "panel" else None
                    mapping = {} if not target else {target: [{"HostIp": "127.0.0.1", "HostPort": str(33000 + index)}]}
                    identity = str(index + 1) * 64
                    self.children[identity] = {"Id": identity,
                        "Config": {"Labels": {"com.docker.compose.project": project, "com.docker.compose.service": name}},
                        "HostConfig": {"PortBindings": mapping}, "NetworkSettings": {"Ports": mapping}}
                if self.fail == "up":
                    raise smoke.SmokeError("up failed after creation")
                return "started"
            if "down" in args:
                self.children.clear()
                return "stopped"
            if "exec" in args:
                self.exec_count += 1
                return json.dumps({"owned_process": True, "world": "Nexus", "durable_sha256": "d" * 64})
        raise AssertionError("Unexpected fake Docker call: " + repr(args))


class Tests(unittest.TestCase):
    def env(self, directory):
        path = Path(directory) / "runtime.env"
        path.write_text("\n".join(name + "=" + "a" * 64 for name in smoke.PINS), encoding="utf-8")
        return path

    def fixture(self, directory, docker=None):
        value = smoke.Smoke(docker or FakeDocker(), Path(directory), Path(directory), PROJECT)
        value.file.write_text("{}", encoding="utf-8")
        return value

    def test_runtime_pins_exact_no_operator_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.env(directory)
            self.assertEqual(set(smoke.runtime_pins(path)), set(smoke.PINS))
            for extra in ("\nNEBULA_ADMIN_TOKEN_SOURCE=/existing", "\n" + smoke.PINS[0] + "=" + "a" * 64):
                path = self.env(directory)
                path.write_text(path.read_text() + extra)
                with self.assertRaises(smoke.SmokeError):
                    smoke.runtime_pins(path)

    def test_runtime_pins_missing_or_uppercase_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.env(directory)
            path.write_text(smoke.PINS[0] + "=" + "A" * 64)
            with self.assertRaises(smoke.SmokeError):
                smoke.runtime_pins(path)

    def test_resolved_config_exposes_only_loopback_http_panel(self):
        config = smoke.private_config(configuration(), PROJECT, IMAGE, IMAGE, Path("/temporary"))
        self.assertEqual(set(config["services"]), smoke.SERVICES)
        for name in ("server", "panel"):
            row = config["services"][name]
            self.assertNotIn("build", row)
            self.assertEqual(row["image"], IMAGE)
            self.assertEqual(row["ports"][0]["published"], "0")
            self.assertEqual(row["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(config["services"]["private-http"]["network_mode"], "service:server")
        self.assertTrue(config["volumes"]["state"]["external"])

    def test_changed_production_security_or_bind_mount_refused(self):
        for change in ("privileged", "user", "volume", "namespace"):
            config = configuration()
            if change == "privileged": config["services"]["server"]["privileged"] = True
            if change == "user": config["services"]["server"]["user"] = "0:0"
            if change == "volume": config["services"]["server"]["volumes"][0]["type"] = "bind"
            if change == "namespace": config["services"]["private-http"]["network_mode"] = "host"
            with self.subTest(change=change), self.assertRaises(smoke.SmokeError):
                smoke.private_config(config, PROJECT, IMAGE, IMAGE, Path("/temporary"))

    def test_existing_volume_is_never_adopted_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory)
            value.docker.volumes[value.volume] = {"Labels": {smoke.LABEL: "someone-else"}}
            with self.assertRaises(smoke.SmokeError): value.create_volume()
            value.cleanup()
            self.assertIn(value.volume, value.docker.volumes)

    def test_timeout_after_volume_create_still_cleans_owned_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory, FakeDocker("volume-create-after-write"))
            with self.assertRaises(smoke.SmokeError): value.create_volume()
            value.cleanup()
            self.assertFalse(value.docker.volumes)

    def test_timed_out_helper_is_removed_by_full_owned_container_id(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory, FakeDocker("helper-timeout"))
            with self.assertRaises(smoke.SmokeError): value.oneoff("seed", IMAGE, ["python", "-c", "pass"])
            value.cleanup()
            calls = [args for args, _ in value.docker.calls if args[:2] == ("container", "rm")]
            self.assertEqual(calls, [("container", "rm", "--force", "c" * 64)])

    def test_cleanup_refuses_changed_helper_or_volume_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory)
            value.created_volume = True
            value.docker.volumes[value.volume] = {"Labels": {smoke.LABEL: "foreign"}}
            with self.assertRaises(smoke.SmokeError): value.cleanup()
            self.assertIn(value.volume, value.docker.volumes)

    def test_failed_up_already_has_cleanup_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory, FakeDocker("up"))
            value.create_volume()
            with self.assertRaises(smoke.SmokeError): value.start()
            value.cleanup()
            self.assertFalse(value.docker.children)
            self.assertFalse(value.docker.volumes)

    def test_unknown_compose_service_refuses_cleanup_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory)
            value.start()
            value.docker.children["1" * 64]["Config"]["Labels"]["com.docker.compose.service"] = "unowned"
            with self.assertRaises(smoke.SmokeError): value.cleanup()
            self.assertTrue(value.docker.children)

    def test_actual_public_management_mapping_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture(directory)
            original = value.containers
            def changed():
                rows = original()
                rows[0]["HostConfig"]["PortBindings"]["8090/tcp"] = [{"HostIp": "0.0.0.0", "HostPort": "8090"}]
                return rows
            with patch.object(value, "containers", changed), self.assertRaises(smoke.SmokeError): value.start()

    def test_outer_flow_restarts_compares_and_cleans_without_real_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            docker = FakeDocker()
            args = SimpleNamespace(runtime_env=self.env(directory), server_image="local-server", panel_image="local-panel", timeout=480)
            with patch.object(smoke.sys, "platform", "linux"), patch.object(smoke.os, "getuid", return_value=1001, create=True), patch.object(smoke.os, "getgid", return_value=1001, create=True), patch.object(smoke.Smoke, "panel") as panel:
                result = smoke.execute(args, docker)
            self.assertEqual(result["result"], "passed")
            self.assertEqual((docker.up_count, docker.exec_count, panel.call_count), (2, 2, 2))
            self.assertFalse(docker.children or docker.volumes)
            runs = [args for args, _ in docker.calls if args[0] == "run"]
            self.assertTrue(all("none" in args and "--read-only" in args for args in runs))

    def test_outer_seed_failure_still_removes_empty_owned_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            docker = FakeDocker("seed")
            args = SimpleNamespace(runtime_env=self.env(directory), server_image="local-server", panel_image="local-panel", timeout=480)
            with patch.object(smoke.sys, "platform", "linux"), patch.object(smoke.os, "getuid", return_value=1001, create=True), patch.object(smoke.os, "getgid", return_value=1001, create=True), self.assertRaises(smoke.SmokeError):
                smoke.execute(args, docker)
            self.assertEqual(docker.up_count, 0)
            self.assertFalse(docker.children or docker.volumes)

    def test_child_failure_suppresses_output_and_operator_environment(self):
        result = SimpleNamespace(returncode=1, stdout="private-password", stderr="private-token")
        with patch.dict(os.environ, {"NEBULA_ADMIN_TOKEN_SOURCE": "/real-secrets", "COMPOSE_PROJECT_NAME": "real-server"}), patch.object(smoke.subprocess, "run", return_value=result) as run:
            with self.assertRaises(smoke.SmokeError) as caught: smoke.Docker().run("version")
            self.assertNotIn("private", str(caught.exception))
            self.assertNotIn("NEBULA_ADMIN_TOKEN_SOURCE", run.call_args.kwargs["env"])
            self.assertNotIn("COMPOSE_PROJECT_NAME", run.call_args.kwargs["env"])
            self.assertEqual(run.call_args.args[0], ["docker", "version"])

    def test_embedded_programs_compile_without_execution(self):
        compile(smoke.SEED, "seed", "exec")
        compile(smoke.PROBE, "probe", "exec")
        self.assertIn("mode=ro", smoke.PROBE)
        self.assertNotIn("Backend(", smoke.PROBE)

    def test_probe_matches_actual_supervisor_argv_and_old_lease_check_fails(self):
        # Compile only the actual production _argv method and the probe's pure
        # checker. No Supervisor construction, process, registry or DB access.
        source = Path(__file__).resolve().parents[1] / "tools/instance_supervisor.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == "Supervisor"
                      for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_argv")
        method.returns = None
        for argument in method.args.args: argument.annotation = None
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "production-argv", "exec"), namespace)
        check = next(node for node in ast.parse(smoke.PROBE).body if isinstance(node, ast.FunctionDef) and node.name == "expected_world_argv")
        exec(compile(ast.Module(body=[check], type_ignores=[]), "probe-argv", "exec"), {"re": re}, namespace)
        row = {"instance_id": "pub-" + "a" * 32, "start_token": "b" * 32, "lease_token": "c" * 32,
               "psidglobal": "Nexus", "readiness_profile": "nonmini-semantic-v1", "port": 28000}
        owner = SimpleNamespace(config=SimpleNamespace(state_dir=PurePosixPath("/var/lib/nebula"),
                    binary=PurePosixPath("/opt/nebula-runtime/build/NebulaServer.x86_64"), bind="0.0.0.0", advertise_ip="127.0.0.1"))
        actual = namespace["_argv"](owner, SimpleNamespace(**row), SimpleNamespace(port=28000), row["start_token"])
        expected = namespace["expected_world_argv"](row)
        self.assertEqual(actual, expected)
        self.assertNotIn(row["lease_token"], actual)  # Exact old probe is false.
        for index in (4, 9, 11, 17, 19, 23, 27):
            changed = actual.copy(); changed[index] = "wrong"
            self.assertNotEqual(changed, expected)
        self.assertNotEqual(actual + ["unexpected-argument"], expected)

    def test_nonlocal_or_wrong_architecture_image_refused(self):
        docker = FakeDocker()
        with patch.object(docker, "json", return_value=[{"Id": IMAGE, "Os": "linux", "Architecture": "arm64"}]):
            with self.assertRaises(smoke.SmokeError): smoke.image_id(docker, "local")
        with patch.object(docker, "json", return_value=[{"Id": "tag-only", "Os": "linux", "Architecture": "amd64"}]):
            with self.assertRaises(smoke.SmokeError): smoke.image_id(docker, "local")


if __name__ == "__main__":
    unittest.main()
