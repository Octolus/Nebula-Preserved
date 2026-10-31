#!/usr/bin/env python3
"""Conservative supervisor for backend-authored Nebula instance demands.

Dry-run is the default.  The supervisor owns only processes that it starts in
the current process lifetime.  Persisted PIDs are observability records, never
an authority to adopt or signal a process after supervisor restart.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


FORMAT_VERSION = 1
SNAPSHOT_PAIR_ATTEMPTS = 3
SNAPSHOT_PAIR_RETRY_SECONDS = 0.01
OPAQUE_INSTANCE_RE = re.compile(r"^(?:apt|pub)-[0-9a-f]{32}$")
SAFE_INSTANCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DESIRED_FIELDS = {
    "instance_id", "kind", "psidglobal", "owner_ps4_id",
    "logical_space_key", "desired_state", "active_demands",
    "pending_reservations", "active_allocations", "adopted_existing",
    "readiness_profile",
}


class ContractError(ValueError):
    pass


class SnapshotPairMismatch(ContractError):
    """A desired/housing pair was not coherent enough to authorize launch."""

    def __init__(self, message: str, observation: dict[str, Any]):
        super().__init__(message)
        self.observation = observation


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"{path} is not a JSON object")
    return value


def _canonical_json_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class DesiredInstance:
    instance_id: str
    kind: str
    psidglobal: str
    owner_ps4_id: str
    logical_space_key: str
    desired_state: str
    active_demands: int
    pending_reservations: int
    active_allocations: int
    adopted_existing: bool
    readiness_profile: str


@dataclass
class Lease:
    desired: DesiredInstance
    port: int
    lease_token: str
    state: str = "reserved"
    pid: int | None = None
    start_token: str = ""
    started_at: float | None = None
    updated_at: float = 0.0
    last_health_at: float | None = None
    restart_count: int = 0
    next_restart_at: float = 0.0
    idle_since: float | None = None
    reason: str = ""


class RealChild:
    def __init__(self, process: subprocess.Popen[bytes], stream: Any):
        self.process = process
        self.stream = stream
        self.pid = process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        if self.poll() is None:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill(self) -> None:
        if self.poll() is None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        self.stream.close()


class ProcessFactory:
    def spawn(self, argv: list[str], cwd: Path, log_path: Path) -> RealChild:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("xb", buffering=0)
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                shell=False,
                close_fds=True,
            )
            return RealChild(process, stream)
        except Exception:
            stream.close()
            raise


class PortProbe:
    def available(self, bind: str, port: int) -> bool:
        family = socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                probe.bind((bind, port))
            except OSError:
                return False
        return True


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                self.stream.write(b"\0")
                self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError("another instance supervisor owns the state directory") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self.stream:
            self.stream.close()


@dataclass
class Config:
    state_dir: Path
    binary: Path
    build_report: Path
    build_report_sha256: str
    binary_sha256: str
    managed_assembly_sha256: str
    bind: str
    advertise_ip: str
    first_port: int
    last_port: int
    max_processes: int
    max_records: int
    allowed_scenes: frozenset[str]
    allowed_profiles: frozenset[str]
    desired_max_age: float = 30.0
    descriptor_max_age: float = 15.0
    startup_timeout: float = 45.0
    poll_interval: float = 1.0
    idle_ttl: float = 0.0
    stop_grace: float = 10.0
    backoff_initial: float = 1.0
    backoff_max: float = 30.0
    run: bool = False
    # None keeps the historical single TTL for public worlds too.
    public_idle_ttl: float | None = None

    @property
    def desired_path(self) -> Path:
        return self.state_dir / "desired-instances.json"

    @property
    def runtime_path(self) -> Path:
        return self.state_dir / "managed-instance-runtime.json"

    @property
    def bindings_path(self) -> Path:
        return self.state_dir / "instance-housing.json"


def validate_build(config: Config) -> str:
    if not config.binary.is_file() or not config.build_report.is_file():
        raise ContractError("pinned binary or build report is missing")
    if os.name != "nt" and not os.access(config.binary, os.X_OK):
        raise ContractError("pinned ELF is not executable")
    if _sha256(config.build_report) != config.build_report_sha256.lower():
        raise ContractError("build report SHA-256 does not match the operator pin")
    actual = _sha256(config.binary)
    if actual != config.binary_sha256.lower():
        raise ContractError("binary SHA-256 does not match the operator pin")
    with config.binary.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ContractError("pinned executable is not an ELF artifact")
    report = _read_json(config.build_report)
    if report.get("exit_code") != 0 or report.get("elf64_x86_64") is not True:
        raise ContractError("build report does not describe a successful ELF64 build")
    managed = config.binary.parent / "NebulaServer_Data" / "Managed" / "Assembly-CSharp.dll"
    if (report.get("executable_sha256") != actual or
            report.get("managed_assembly_sha256") != config.managed_assembly_sha256.lower() or
            not managed.is_file() or _sha256(managed) != config.managed_assembly_sha256.lower()):
        raise ContractError("build report or managed assembly does not match the operator pins")
    sources = report.get("source_hashes")
    if (not isinstance(sources, list) or not sources or any(
            not isinstance(row, dict) or set(row) != {"path", "sha256"} or
            not isinstance(row["path"], str) or not re.fullmatch(r"[0-9a-f]{64}", str(row["sha256"]))
            for row in sources)):
        raise ContractError("build report source hash manifest is malformed")
    matches = [row for row in report.get("artifacts", [])
               if isinstance(row, dict) and row.get("path") == config.binary.name]
    if len(matches) != 1 or matches[0].get("sha256") != actual or matches[0].get("size") != config.binary.stat().st_size:
        raise ContractError("build report does not pin the exact executable")
    return actual


def _validated_ipv4(value: str, label: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ContractError(f"{label} is not an IP address") from exc
    if address.version != 4 or address.is_multicast or address.is_unspecified and label == "advertise_ip":
        raise ContractError(f"{label} must be a usable IPv4 address")
    return str(address)


class Supervisor:
    def __init__(self, config: Config, *, clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic,
                 processes: Any | None = None, ports: Any | None = None,
                 token: Callable[[], str] | None = None):
        self.config = config
        self.clock = clock
        self.monotonic = monotonic
        self.processes = processes or ProcessFactory()
        self.ports = ports or PortProbe()
        self.token = token or (lambda: secrets.token_hex(16))
        self.children: dict[str, Any] = {}
        self.stop_requested: dict[str, float] = {}
        self.leases: dict[str, Lease] = {}
        self.desired_generation = 0.0
        self.binary_sha = validate_build(config)
        self.minimum_generation = 0.0
        self._load_runtime_observations()

    def _load_runtime_observations(self) -> None:
        path = self.config.runtime_path
        if not path.exists():
            return
        value = _read_json(path)
        if value.get("format_version") != FORMAT_VERSION:
            raise ContractError("unsupported managed runtime snapshot")
        journal_generation = value.get("generation")
        desired_generation = value.get("desired_generation")
        if (not isinstance(journal_generation, (int, float)) or isinstance(journal_generation, bool) or
                not math.isfinite(float(journal_generation)) or
                not isinstance(desired_generation, (int, float)) or isinstance(desired_generation, bool) or
                not math.isfinite(float(desired_generation))):
            raise ContractError("managed runtime generation watermark is invalid")
        self.minimum_generation = max(self.minimum_generation, float(desired_generation))
        if not isinstance(value.get("instances"), list) or len(value["instances"]) > self.config.max_records:
            raise ContractError("managed runtime record count exceeds the operator limit")
        seen_ports: set[int] = set()
        seen_tokens: set[str] = set()
        seen_ids: set[str] = set()
        for row in value["instances"]:
            if not isinstance(row, dict) or not SAFE_INSTANCE_RE.fullmatch(str(row.get("instance_id", ""))):
                raise ContractError("malformed persisted runtime row")
            if row["instance_id"] in seen_ids:
                raise ContractError("persisted instance ID is duplicated")
            seen_ids.add(row["instance_id"])
            port = row.get("port")
            if not isinstance(port, int) or not self.config.first_port <= port <= self.config.last_port or port in seen_ports:
                raise ContractError("persisted port lease is invalid or duplicated")
            seen_ports.add(port)
            lease_token = row.get("lease_token")
            if not isinstance(lease_token, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_token) or lease_token in seen_tokens:
                raise ContractError("persisted lease token is invalid or duplicated")
            seen_tokens.add(lease_token)
            recorded_generation = row.get("desired_generation", 0.0)
            if (not isinstance(recorded_generation, (int, float)) or isinstance(recorded_generation, bool) or
                    not math.isfinite(float(recorded_generation))):
                raise ContractError("persisted desired generation is invalid")
            self.minimum_generation = max(self.minimum_generation, float(recorded_generation))
            restart_count = row.get("restart_count", 0)
            next_restart_at = row.get("next_restart_at", 0.0)
            if (type(restart_count) is not int or not 0 <= restart_count <= 31 or
                    not isinstance(next_restart_at, (int, float)) or isinstance(next_restart_at, bool) or
                    not math.isfinite(float(next_restart_at)) or float(next_restart_at) < 0 or
                    float(next_restart_at) > self.clock() + self.config.backoff_max + 2.0):
                raise ContractError("persisted restart backoff is invalid")
            # Never adopt or signal this PID. Preserve only the durable lease.
            placeholder = DesiredInstance(str(row["instance_id"]), str(row.get("kind", "public")),
                                          str(row.get("psidglobal", "")), str(row.get("owner_ps4_id", "")),
                                          str(row.get("logical_space_key", "")), "running", 0, 0, 0,
                                          bool(row.get("adopted_existing", False)),
                                          str(row.get("readiness_profile", "")))
            self.leases[placeholder.instance_id] = Lease(
                placeholder, port, lease_token,
                state="orphaned_observation", updated_at=self.clock(),
                restart_count=restart_count,
                next_restart_at=float(next_restart_at),
                reason="persisted PID deliberately not adopted",
            )
        self.desired_generation = max(self.desired_generation, self.minimum_generation)

    def _bindings(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        try:
            value = _read_json(self.config.bindings_path)
        except FileNotFoundError:
            # Atomic replacement is observed as a brief disappearance on some
            # cross-platform filesystems. Public-only intent does not require
            # this registry; personal rows below still fail unless a retry
            # obtains their exact authoritative bindings.
            return {}, {
                "present": False,
                "generation": None,
                "canonical_json_sha256": None,
                "binding_count": 0,
                "read_error": "file_not_found",
            }
        if value.get("format_version") != FORMAT_VERSION:
            raise ContractError("unsupported housing binding snapshot")
        generation = value.get("generation")
        now = self.clock()
        if (not isinstance(generation, (int, float)) or isinstance(generation, bool) or
                not math.isfinite(float(generation)) or float(generation) > now + 2.0 or
                now - float(generation) > self.config.desired_max_age):
            raise ContractError("housing binding snapshot is not fresh")
        rows = value.get("bindings")
        if not isinstance(rows, list):
            raise ContractError("housing bindings must be a list")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("instance_id"), str) or row["instance_id"] in result:
                raise ContractError("housing binding rows must have unique instance IDs")
            result[row["instance_id"]] = row
        return result, {
            "present": True,
            "generation": float(generation),
            "canonical_json_sha256": _canonical_json_sha256(value),
            "binding_count": len(result),
        }

    def load_desired(self) -> list[DesiredInstance]:
        observations: list[dict[str, Any]] = []
        last_error: SnapshotPairMismatch | None = None
        for attempt in range(SNAPSHOT_PAIR_ATTEMPTS):
            try:
                return self._load_desired_once()
            except SnapshotPairMismatch as error:
                last_error = error
                observations.append({"attempt": attempt + 1, **error.observation})
                if attempt + 1 < SNAPSHOT_PAIR_ATTEMPTS:
                    time.sleep(SNAPSHOT_PAIR_RETRY_SECONDS)
        assert last_error is not None
        if self.config.run:
            self._record_snapshot_pair_failure(observations, str(last_error))
        raise last_error

    def _record_snapshot_pair_failure(self, observations: list[dict[str, Any]], error: str) -> None:
        diagnostic = {
            "format_version": FORMAT_VERSION,
            "recorded_at": self.clock(),
            "kind": "desired_housing_snapshot_pair_failure",
            "attempt_limit": SNAPSHOT_PAIR_ATTEMPTS,
            "error": error,
            "observations": observations,
            "redaction": "Instance IDs are SHA-256 only; owner IDs and binding values are omitted.",
        }
        try:
            _atomic_json(self.config.state_dir / "snapshot-pair-failure.json", diagnostic)
        except Exception:
            # Evidence retention must never replace the authoritative failure.
            pass

    def _load_desired_once(self) -> list[DesiredInstance]:
        try:
            value = _read_json(self.config.desired_path)
        except FileNotFoundError:
            raise SnapshotPairMismatch("desired snapshot disappeared during validation", {
                "desired_first": {
                    "present": False,
                    "generation": None,
                    "canonical_json_sha256": None,
                    "read_error": "file_not_found",
                },
                "housing": None,
                "desired_second": None,
                "desired_changed_during_read": True,
                "personal_mismatches": [],
            })
        if set(value) != {"format_version", "generation", "managed", "instances"}:
            raise ContractError("desired snapshot has unknown or missing top-level fields")
        if value["format_version"] != FORMAT_VERSION or value["managed"] is not True:
            raise ContractError("desired snapshot is not an enabled v1 managed snapshot")
        generation = value["generation"]
        if (not isinstance(generation, (int, float)) or isinstance(generation, bool) or
                not math.isfinite(float(generation))):
            raise ContractError("desired generation must be a Unix timestamp")
        now = self.clock()
        if generation > now + 2.0 or now - float(generation) > self.config.desired_max_age:
            raise ContractError("desired snapshot is not fresh")
        if float(generation) < self.minimum_generation:
            raise ContractError("desired snapshot generation rolled back")
        rows = value["instances"]
        if not isinstance(rows, list) or len(rows) > self.config.max_records:
            raise ContractError("desired instance record count exceeds the operator limit")
        bindings, housing_observation = self._bindings()
        try:
            repeated = _read_json(self.config.desired_path)
        except FileNotFoundError:
            raise SnapshotPairMismatch("desired snapshot disappeared during validation", {
                "desired_first": {
                    "present": True,
                    "generation": float(generation),
                    "canonical_json_sha256": _canonical_json_sha256(value),
                    "instance_count": len(rows),
                },
                "housing": housing_observation,
                "desired_second": {
                    "present": False,
                    "generation": None,
                    "canonical_json_sha256": None,
                    "read_error": "file_not_found",
                },
                "desired_changed_during_read": True,
                "personal_mismatches": [],
            })
        repeated_generation = repeated.get("generation")
        if (not isinstance(repeated_generation, (int, float)) or isinstance(repeated_generation, bool) or
                not math.isfinite(float(repeated_generation))):
            repeated_generation = None
        observation = {
            "desired_first": {
                "present": True,
                "generation": float(generation),
                "canonical_json_sha256": _canonical_json_sha256(value),
                "instance_count": len(rows),
            },
            "housing": housing_observation,
            "desired_second": {
                "present": True,
                "generation": None if repeated_generation is None else float(repeated_generation),
                "canonical_json_sha256": _canonical_json_sha256(repeated),
            },
            "desired_changed_during_read": repeated != value,
            "personal_mismatches": [],
        }
        if repeated != value:
            raise SnapshotPairMismatch("desired and housing snapshots changed during validation", observation)
        result: list[DesiredInstance] = []
        seen: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict) or set(raw) != DESIRED_FIELDS:
                raise ContractError("desired row has unknown or missing fields")
            row = DesiredInstance(**raw)
            if any(not isinstance(field, str) for field in (
                    row.instance_id, row.kind, row.psidglobal, row.owner_ps4_id,
                    row.logical_space_key, row.desired_state, row.readiness_profile)):
                raise ContractError("desired identity and policy fields must be strings")
            if (not SAFE_INSTANCE_RE.fullmatch(row.instance_id) or row.instance_id in seen or
                    (not row.adopted_existing and not OPAQUE_INSTANCE_RE.fullmatch(row.instance_id))):
                raise ContractError("instance ID is neither a new opaque ID nor an explicitly adopted safe ID")
            seen.add(row.instance_id)
            if row.kind not in {"public", "personal"} or row.desired_state not in {"running", "stopped"}:
                raise ContractError("unsupported instance kind or desired state")
            if row.psidglobal not in self.config.allowed_scenes or row.readiness_profile not in self.config.allowed_profiles:
                raise ContractError("scene or readiness profile is not operator-allowed")
            if (not isinstance(row.adopted_existing, bool) or any(
                    not isinstance(value, int) or isinstance(value, bool) or value < 0
                    for value in (row.active_demands, row.pending_reservations, row.active_allocations))):
                raise ContractError("desired demand counters must be nonnegative integers")
            if row.desired_state == "stopped" and any(
                    (row.active_demands, row.pending_reservations, row.active_allocations)):
                raise ContractError("stopped instance still carries active demand state")
            if row.kind == "public":
                if row.owner_ps4_id or row.logical_space_key:
                    raise ContractError("public desired row carries personal ownership")
            else:
                if not row.owner_ps4_id or not row.logical_space_key:
                    raise ContractError("personal desired row is missing its binding")
                binding = bindings.get(row.instance_id)
                expected = (row.instance_id, row.psidglobal, row.owner_ps4_id, row.logical_space_key)
                actual = () if not binding else tuple(binding.get(key) for key in
                    ("instance_id", "psidglobal", "owner_ps4_id", "logical_space_key"))
                if actual != expected:
                    fields = ("instance_id", "psidglobal", "owner_ps4_id", "logical_space_key")
                    observation["personal_mismatches"].append({
                        "instance_id_sha256": hashlib.sha256(row.instance_id.encode("utf-8")).hexdigest(),
                        "classification": "binding_missing" if binding is None else "binding_fields_differ",
                        "differing_fields": list(fields) if binding is None else [
                            key for key in fields if binding.get(key) != getattr(row, key)
                        ],
                    })
            result.append(row)
        if observation["personal_mismatches"]:
            raise SnapshotPairMismatch(
                "personal desired row disagrees with authoritative housing binding", observation)
        if [row.instance_id for row in result] != sorted(row.instance_id for row in result):
            raise ContractError("desired instances are not sorted by instance_id")
        self.desired_generation = float(generation)
        self.minimum_generation = max(self.minimum_generation, self.desired_generation)
        return result

    def _allocate_port(self) -> int:
        used = {lease.port for lease in self.leases.values()}
        for port in range(self.config.first_port, self.config.last_port + 1):
            if port not in used and self.ports.available(self.config.bind, port):
                return port
        raise RuntimeError("no collision-free port remains in the bounded range")

    def _argv(self, desired: DesiredInstance, lease: Lease, attempt_token: str) -> list[str]:
        log = (self.config.state_dir / "supervisor-logs" / desired.instance_id /
               f"{attempt_token}.unity.log")
        # Shipped minigame managers (board, darts, pool, bowling); the scene
        # runtime refuses any other count (NebulaCoreReadiness.SceneTables,
        # backend allocation.MINIGAME_SCENE_TABLES). Kept local to this method.
        tables = {
            "StoneLakeCastle": (8, 0, 0, 0),
            "Bowling": (0, 3, 9, 12),
        }.get(desired.psidglobal, (0, 0, 0, 0))
        return [
            str(self.config.binary), "-batchmode", "-nographics", "-logFile", str(log),
            "--nebula-instance", "--nebula-state-dir", str(self.config.state_dir),
            "--nebula-instance-id", desired.instance_id,
            "--nebula-space", desired.psidglobal,
            "--nebula-bind", self.config.bind,
            "--nebula-advertise-ip", self.config.advertise_ip,
            "--nebula-port", str(lease.port),
            "--nebula-board-tables", str(tables[0]), "--nebula-darts-tables", str(tables[1]),
            "--nebula-pool-tables", str(tables[2]), "--nebula-bowling-lanes", str(tables[3]),
            "--nebula-core-test-profile", desired.readiness_profile,
        ]

    def _descriptor_healthy(self, lease: Lease, now: float) -> bool:
        path = self.config.state_dir / "instances" / lease.desired.instance_id / "instance-status.json"
        try:
            value = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        expected = {
            "format_version": 1,
            "instance_id": lease.desired.instance_id,
            "psidglobal": lease.desired.psidglobal,
            "ip": self.config.advertise_ip,
            "bind": self.config.bind,
            "port": lease.port,
            "readiness_scope": lease.desired.readiness_profile,
        }
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            return False
        heartbeat = value.get("heartbeat")
        if (not isinstance(heartbeat, (int, float)) or isinstance(heartbeat, bool) or
                not math.isfinite(float(heartbeat)) or
                float(heartbeat) > now + 2.0 or now - float(heartbeat) > self.config.descriptor_max_age):
            return False
        if lease.started_at is not None and float(heartbeat) < lease.started_at:
            return False
        # Observe real listener state, but never manufacture readiness/parity.
        return value.get("listener_bound") is True and value.get("listening") is True

    def _request_stop(self, instance_id: str, reason: str) -> None:
        child = self.children.get(instance_id)
        lease = self.leases[instance_id]
        if not child:
            lease.state = "stopped"
            lease.reason = reason
            lease.pid = None
            return
        if instance_id not in self.stop_requested:
            child.terminate()
            self.stop_requested[instance_id] = self.monotonic()
            lease.state = "draining"
            lease.reason = reason

    def _set_backoff(self, lease: Lease, now: float) -> None:
        lease.restart_count = min(31, lease.restart_count + 1)
        exponent = min(30, max(0, lease.restart_count - 1))
        delay = min(self.config.backoff_max, self.config.backoff_initial * (2 ** exponent))
        lease.next_restart_at = now + delay
        lease.state = "backoff"

    def _reap(self, now: float) -> None:
        for instance_id, child in list(self.children.items()):
            code = child.poll()
            lease = self.leases[instance_id]
            if code is None:
                started = self.stop_requested.get(instance_id)
                if started is not None and self.monotonic() - started >= self.config.stop_grace:
                    child.kill()
                continue
            child.close()
            self.children.pop(instance_id, None)
            requested = self.stop_requested.pop(instance_id, None) is not None
            stopped_for_idle = requested and lease.reason == "idle TTL"
            evicted = requested and lease.reason == "capacity eviction"
            lease.pid = None
            if requested:
                lease.restart_count = 0
                lease.next_restart_at = now
            else:
                self._set_backoff(lease, now)
            lease.state = ("stopped_idle" if stopped_for_idle else "evicted" if evicted
                           else "stopped" if requested else "backoff")
            lease.reason = f"owned child exited with code {code}"

    def step(self) -> list[dict[str, Any]]:
        desired_rows = self.load_desired()
        now = self.clock()
        self._reap(now)
        desired = {row.instance_id: row for row in desired_rows}
        actions: list[dict[str, Any]] = []
        planned_dry_run_launches = 0
        queued: list[str] = []

        for instance_id in sorted(set(self.leases) - set(desired)):
            if instance_id in self.children:
                if self.config.run:
                    self._request_stop(instance_id, "removed from desired snapshot")
                actions.append({"action": "stop", "instance_id": instance_id, "reason": "not desired"})
            elif self.ports.available(self.config.bind, self.leases[instance_id].port):
                del self.leases[instance_id]

        for row in desired_rows:
            lease = self.leases.get(row.instance_id)
            if row.desired_state == "stopped":
                if lease is not None:
                    lease.desired = row
                    lease.updated_at = now
                    if row.instance_id in self.children:
                        actions.append({"action": "stop", "instance_id": row.instance_id,
                                        "reason": "backend desired_state stopped"})
                        if self.config.run:
                            self._request_stop(row.instance_id, "backend desired_state stopped")
                    else:
                        if self.ports.available(self.config.bind, lease.port):
                            del self.leases[row.instance_id]
                        else:
                            lease.state = "collision"
                            lease.reason = "stopped lease remains occupied by an unowned process"
                continue
            idle = (row.active_demands == 0 and row.pending_reservations == 0 and
                    row.active_allocations == 0)
            live = self.children.get(row.instance_id)
            if idle and not (live and live.poll() is None):
                # Backend idle grace keeps a live world warm; it never justifies a launch.
                continue
            budget_used = len(self.children) + (planned_dry_run_launches if not self.config.run else 0)
            if lease is None and budget_used >= self.config.max_processes:
                actions.append({"action": "queue", "instance_id": row.instance_id,
                                "reason": "owned process budget is full"})
                queued.append(row.instance_id)
                continue
            if lease is None:
                try:
                    port = self._allocate_port()
                except RuntimeError:
                    actions.append({"action": "queue", "instance_id": row.instance_id,
                                    "reason": "no collision-free leased port is available"})
                    continue
                lease = Lease(row, port, self.token(), updated_at=now)
                self.leases[row.instance_id] = lease
            else:
                lease.desired = row
            lease.updated_at = now

            child = self.children.get(row.instance_id)
            if child and child.poll() is None:
                if row.instance_id in self.stop_requested:
                    lease.state = "draining"
                    continue
                lease.state = "healthy" if self._descriptor_healthy(lease, now) else "starting"
                if lease.state == "healthy":
                    lease.last_health_at = now
                elif ((lease.last_health_at is not None and
                       now - lease.last_health_at > self.config.descriptor_max_age) or
                      (lease.last_health_at is None and lease.started_at is not None and
                       now - lease.started_at > self.config.startup_timeout)):
                    actions.append({"action": "stop", "instance_id": row.instance_id,
                                    "reason": "actual descriptor health timed out"})
                    if self.config.run:
                        self._request_stop(row.instance_id, "actual descriptor health timed out")
                    continue
                if idle:
                    lease.idle_since = lease.idle_since or now
                    ttl = self._idle_ttl(row)
                    if ttl > 0 and now - lease.idle_since >= ttl:
                        actions.append({"action": "stop", "instance_id": row.instance_id, "reason": "idle TTL"})
                        if self.config.run:
                            self._request_stop(row.instance_id, "idle TTL")
                else:
                    lease.idle_since = None
                continue

            budget_used = len(self.children) + (planned_dry_run_launches if not self.config.run else 0)
            if budget_used >= self.config.max_processes:
                actions.append({"action": "queue", "instance_id": row.instance_id,
                                "reason": "owned process budget is full"})
                queued.append(row.instance_id)
                continue
            if now < lease.next_restart_at:
                continue
            if not self.ports.available(self.config.bind, lease.port):
                lease.state = "collision"
                lease.reason = "leased endpoint is occupied by an unowned process"
                actions.append({"action": "refuse", "instance_id": row.instance_id,
                                "port": lease.port, "reason": lease.reason})
                continue
            attempt_token = "planned-attempt"
            if self.config.run:
                attempt_token = self.token()
                if (not re.fullmatch(r"[0-9a-f]{32}", attempt_token) or
                        attempt_token == lease.start_token):
                    raise RuntimeError("attempt token is invalid or reused")
            argv = self._argv(row, lease, attempt_token)
            actions.append({"action": "launch", "instance_id": row.instance_id,
                            "port": lease.port, "start_token": attempt_token, "argv": argv})
            if not self.config.run:
                planned_dry_run_launches += 1
            if self.config.run:
                log = (self.config.state_dir / "supervisor-logs" / row.instance_id /
                       f"{attempt_token}.process.log")
                unity_log = Path(argv[argv.index("-logFile") + 1])
                if log.exists() or unity_log.exists():
                    raise RuntimeError("attempt log path already exists")
                lease.pid = None
                lease.start_token = attempt_token
                lease.started_at = now
                lease.last_health_at = None
                lease.idle_since = None
                lease.state = "launch_intent"
                lease.reason = "lease persisted before child creation"
                self.write_runtime()
                try:
                    child = self.processes.spawn(argv, self.config.binary.parent, log)
                except Exception as exc:
                    self._set_backoff(lease, now)
                    lease.reason = f"spawn failed: {type(exc).__name__}"
                    self.write_runtime()
                    actions.append({"action": "spawn_failed", "instance_id": row.instance_id,
                                    "port": lease.port, "reason": lease.reason})
                    continue
                self.children[row.instance_id] = child
                lease.pid = child.pid
                lease.state = "starting"
                lease.reason = ""

        self._evict_for(queued, desired, now, actions)
        if self.config.run:
            self.write_runtime()
        return actions

    def _idle_ttl(self, row: DesiredInstance) -> float:
        if row.kind == "public" and self.config.public_idle_ttl is not None:
            return self.config.public_idle_ttl
        return self.config.idle_ttl

    def _evict_for(self, queued: list[str], desired: dict[str, DesiredInstance], now: float,
                   actions: list[dict[str, Any]]) -> None:
        """Stop warm EMPTY worlds only when a real demand is queued on the budget.

        A world is a candidate only when the backend reports zero demands,
        reservations and allocations (its idle grace). Personal worlds go first,
        then public ones, least recently active first. Occupied worlds are never
        candidates, and slots already draining are credited before evicting more.
        """
        draining = sum(1 for instance_id in self.stop_requested if instance_id in self.children)
        needed = len(queued) - draining
        if needed <= 0:
            return
        candidates = []
        for instance_id, child in self.children.items():
            row = desired.get(instance_id)
            if (row is None or instance_id in self.stop_requested or child.poll() is not None or
                    row.desired_state != "running" or
                    any((row.active_demands, row.pending_reservations, row.active_allocations))):
                continue
            idle_since = self.leases[instance_id].idle_since
            candidates.append((row.kind != "personal", now if idle_since is None else idle_since, instance_id))
        for _public, _since, instance_id in sorted(candidates)[:needed]:
            actions.append({"action": "evict", "instance_id": instance_id,
                            "reason": "capacity eviction", "for": queued})
            if self.config.run:
                self._request_stop(instance_id, "capacity eviction")

    def write_runtime(self) -> None:
        rows = []
        for instance_id in sorted(self.leases):
            lease = self.leases[instance_id]
            row = {
                "instance_id": instance_id,
                "kind": lease.desired.kind,
                "psidglobal": lease.desired.psidglobal,
                "owner_ps4_id": lease.desired.owner_ps4_id,
                "logical_space_key": lease.desired.logical_space_key,
                "readiness_profile": lease.desired.readiness_profile,
                "adopted_existing": lease.desired.adopted_existing,
                "port": lease.port,
                "lease_token": lease.lease_token,
                "pid": lease.pid,
                "start_token": lease.start_token,
                "build_sha256": self.binary_sha,
                "desired_generation": self.desired_generation,
                "state": lease.state,
                "started_at": lease.started_at,
                "last_health_at": lease.last_health_at,
                "restart_count": lease.restart_count,
                "next_restart_at": lease.next_restart_at,
                "updated_at": lease.updated_at,
                "reason": lease.reason,
            }
            rows.append(row)
        _atomic_json(self.config.runtime_path, {
            "format_version": FORMAT_VERSION,
            "generation": self.clock(),
            "desired_generation": max(self.desired_generation, self.minimum_generation),
            "instances": rows,
        })

    def shutdown(self) -> None:
        if not self.config.run:
            return
        for instance_id in list(self.children):
            self._request_stop(instance_id, "supervisor shutdown")
        deadline = self.monotonic() + self.config.stop_grace
        while self.children and self.monotonic() < deadline:
            self._reap(self.clock())
            if self.children:
                time.sleep(min(0.1, self.config.poll_interval))
        for child in self.children.values():
            child.kill()
        # A signal is not proof of exit. poll() reaps each actual owned Popen.
        reap_deadline = self.monotonic() + 3.0
        while self.children:
            self._reap(self.clock())
            if not self.children or self.monotonic() >= reap_deadline:
                break
            time.sleep(min(0.1, max(0.0, reap_deadline - self.monotonic())))
        for instance_id in self.children:
            self.leases[instance_id].reason = "owned child exit unconfirmed after shutdown kill"
        self.write_runtime()
        if self.children:
            raise RuntimeError("owned children did not exit within the shutdown reap deadline")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="launch processes; default is read-only dry-run")
    parser.add_argument("--once", action="store_true", help="perform one reconciliation")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--build-report-sha256", required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--managed-assembly-sha256", required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--advertise-ip", required=True)
    parser.add_argument("--port-range", required=True, metavar="FIRST-LAST")
    parser.add_argument("--max-processes", type=int, default=16)
    parser.add_argument("--max-records", type=int, default=4096)
    parser.add_argument("--allowed-scene", action="append", required=True)
    parser.add_argument("--allowed-profile", action="append", required=True)
    parser.add_argument("--desired-max-age", type=float, default=30.0)
    parser.add_argument("--descriptor-max-age", type=float, default=15.0)
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--idle-ttl", type=float, default=0.0,
                        help="seconds an empty personal (and, by default, public) world stays warm; 0 disables")
    parser.add_argument("--public-idle-ttl", type=float, default=None,
                        help="separate idle TTL for public/shared worlds such as Nexus")
    parser.add_argument("--stop-grace", type=float, default=10.0)
    parser.add_argument("--backoff-initial", type=float, default=1.0)
    parser.add_argument("--backoff-max", type=float, default=30.0)
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> Config:
    try:
        first, last = (int(value) for value in args.port_range.split("-", 1))
    except (ValueError, AttributeError) as exc:
        raise ContractError("port range must be FIRST-LAST") from exc
    if (not 1 <= first <= last <= 65535 or args.max_processes < 1 or
            not args.max_processes <= args.max_records <= 65536 or
            last - first + 1 < args.max_processes):
        raise ContractError("port range or max process count is invalid")
    if min(args.desired_max_age, args.descriptor_max_age, args.startup_timeout, args.poll_interval,
           args.stop_grace, args.backoff_initial) <= 0 or args.backoff_max < args.backoff_initial:
        raise ContractError("timing bounds are invalid")
    if args.idle_ttl < 0 or (args.public_idle_ttl is not None and args.public_idle_ttl < 0):
        raise ContractError("idle TTLs must be nonnegative")
    if args.run and os.name != "posix":
        raise ContractError("--run is supported only on a Linux/POSIX host")
    if args.run and args.once:
        raise ContractError("--once is a dry-run inspection mode and cannot launch children")
    return Config(
        args.state_dir.resolve(), args.binary.resolve(), args.build_report.resolve(),
        args.build_report_sha256.lower(), args.binary_sha256.lower(), args.managed_assembly_sha256.lower(),
        _validated_ipv4(args.bind, "bind"),
        _validated_ipv4(args.advertise_ip, "advertise_ip"), first, last,
        args.max_processes, args.max_records, frozenset(args.allowed_scene), frozenset(args.allowed_profile),
        args.desired_max_age, args.descriptor_max_age, args.startup_timeout, args.poll_interval,
        args.idle_ttl, args.stop_grace, args.backoff_initial, args.backoff_max, args.run,
        args.public_idle_ttl,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = config_from_args(args)
    ownership = FileLock(config.state_dir / "instance-supervisor.lock") if config.run else nullcontext()
    with ownership:
        supervisor = Supervisor(config)
        stop = threading.Event()
        if config.run:
            def request_stop(_signum: int, _frame: Any) -> None:
                stop.set()
            signal.signal(signal.SIGTERM, request_stop)
            signal.signal(signal.SIGINT, request_stop)
        try:
            while not stop.is_set():
                actions = supervisor.step()
                # Idle polls are silent; --once always reports for inspection.
                if actions or args.once:
                    print(json.dumps({"dry_run": not config.run, "actions": actions}, sort_keys=True), flush=True)
                if args.once:
                    return 0
                stop.wait(config.poll_interval)
            return 0
        finally:
            supervisor.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, RuntimeError) as exc:
        print(f"instance-supervisor: {exc}", file=sys.stderr)
        raise SystemExit(2)
