"""World capacity: idle grace, noFreeSlot admission and supervisor eviction of empty worlds only."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from instance_lifecycle import lifecycle_policy
import test_instance_lifecycle as fixture

SPEC = importlib.util.spec_from_file_location("capacity_supervisor", BACKEND.parent / "tools/instance_supervisor.py")
SUPERVISOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUPERVISOR  # dataclasses resolve their module.
SPEC.loader.exec_module(SUPERVISOR)


class LifecycleCapacity(unittest.TestCase):
    setUp = fixture.ManagedInstanceTests.setUp
    tearDown = fixture.ManagedInstanceTests.tearDown
    account = fixture.ManagedInstanceTests.account
    descriptor = fixture.ManagedInstanceTests.descriptor
    presence = fixture.ManagedInstanceTests.presence
    load = fixture.ManagedInstanceTests.load
    poll = fixture.ManagedInstanceTests.poll

    def demand_instance(self, guid):
        return self.store.db.execute("SELECT instance_id FROM instance_demands WHERE requester_guid=?",
                                     (guid,)).fetchone()[0]

    def desired(self, instance_id):
        rows = json.loads(self.service.lifecycle.export_desired(self.root).read_text())["instances"]
        return next(row for row in rows if row["instance_id"] == instance_id)

    def leave(self, guid, instance_id, scene, idle_for=None):
        if (self.root / "instances" / instance_id).is_dir():
            self.presence(instance_id, scene, [])
        with self.store.db:
            self.store.db.execute("UPDATE instance_demands SET expires_at=? WHERE requester_guid=?",
                                  (time.time() - 1, guid))
            if idle_for is not None:
                self.store.db.execute("UPDATE managed_instances SET last_active_at=? WHERE instance_id=?",
                                      (time.time() - idle_for, instance_id))

    def test_policy_defaults_and_operator_overrides(self):
        self.assertEqual(lifecycle_policy({}), {"idle_seconds": {"public": 900.0, "personal": 60.0},
                                                "max_worlds": None})
        policy = lifecycle_policy({"NEBULA_IDLE_TTL": "45", "NEBULA_PUBLIC_WORLD_IDLE_SECONDS": "30",
                                   "NEBULA_MAX_PROCESSES": "4"})
        self.assertEqual((policy["idle_seconds"], policy["max_worlds"]), ({"public": 30.0, "personal": 45.0}, 4))
        self.assertEqual(lifecycle_policy({"NEBULA_IDLE_TTL": "45", "NEBULA_PERSONAL_WORLD_IDLE_SECONDS": "5"})
                         ["idle_seconds"]["personal"], 5.0)
        for env in ({"NEBULA_PUBLIC_WORLD_IDLE_SECONDS": "-1"}, {"NEBULA_MAX_PROCESSES": "0"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                lifecycle_policy(env)

    def test_empty_nexus_stays_warm_for_public_grace_then_stops(self):
        guid = self.account("visitor")
        self.assertEqual(self.load(guid, "visitor", "Login"), guid + "#false#false")
        nexus = self.demand_instance(guid)
        self.descriptor(nexus, "Nexus")
        self.assertIn("#true#", self.poll(guid, "visitor"))
        self.presence(nexus, "Nexus", [guid])
        self.assertEqual(self.desired(nexus)["desired_state"], "running")
        self.leave(guid, nexus, "Nexus", idle_for=120)  # Past the personal grace, inside the public one.
        warm = self.desired(nexus)
        self.assertEqual((warm["desired_state"], warm["active_demands"], warm["pending_reservations"],
                          warm["active_allocations"]), ("running", 0, 0, 0))
        self.leave(guid, nexus, "Nexus", idle_for=901)
        self.assertEqual(self.desired(nexus)["desired_state"], "stopped")

    def test_full_budget_answers_native_no_free_slot_without_reserving(self):
        self.service.lifecycle.max_worlds = 1
        owner = self.account("owner")
        self.assertEqual(self.load(owner, "owner"), owner + "#false#false")
        home = self.demand_instance(owner)
        other = self.account("other")
        self.assertEqual(self.load(other, "other"), other + "#false#true")
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM instance_demands WHERE requester_guid=?",
                                                (other,)).fetchone())
        public = self.account("public")
        self.assertEqual(self.load(public, "public", "Login"), public + "#false#true")
        self.assertIsNone(self.store.db.execute("SELECT 1 FROM managed_instances WHERE kind='public'").fetchone())
        # An empty world in idle grace is evictable, so it never blocks admission.
        self.leave(owner, home, "Home")
        self.assertEqual(self.desired(home)["desired_state"], "running")
        self.assertEqual(self.load(other, "other"), other + "#false#false")

    def test_already_running_target_is_admitted_at_full_budget(self):
        self.service.lifecycle.max_worlds = 1
        owner = self.account("owner")
        self.load(owner, "owner")
        self.descriptor("pub-" + "a" * 32, "Nexus")
        visitor = self.account("visitor")
        self.assertEqual(self.load(visitor, "visitor", "Login"), visitor + "#false#false")
        self.assertEqual(self.demand_instance(visitor), "pub-" + "a" * 32)


class Child:
    def __init__(self, pid):
        self.pid, self.code, self.terminated = pid, None, False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, 0

    def kill(self):
        self.code = -9

    def close(self):
        pass


class Processes:
    def __init__(self):
        self.spawned = []

    def spawn(self, argv, cwd, log):
        child = Child(1000 + len(self.spawned))
        self.spawned.append((argv[argv.index("--nebula-instance-id") + 1], child))
        return child


class Ports:
    def available(self, bind, port):
        return True


def row(instance_id, kind="personal", demands=0, allocations=0, state="running"):
    personal = kind == "personal"
    return SUPERVISOR.DesiredInstance(instance_id, kind, "Home" if personal else "Nexus",
                                      "owner-" + instance_id if personal else "", "Home" if personal else "",
                                      state, demands, 0, allocations, False, "nonmini-semantic-v1")


class SupervisorEviction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000.0
        self.processes = Processes()
        root = Path(self.temp.name)
        config = SUPERVISOR.Config(root, root / "NebulaServer.x86_64", root / "report.json", "0" * 64, "0" * 64,
                                   "0" * 64, "127.0.0.1", "127.0.0.1", 28000, 28031, 2, 64,
                                   frozenset({"Nexus", "Home"}), frozenset({"nonmini-semantic-v1"}),
                                   idle_ttl=60.0, run=True, public_idle_ttl=900.0)
        with patch.object(SUPERVISOR, "validate_build", return_value="0" * 64):
            self.supervisor = SUPERVISOR.Supervisor(config, clock=lambda: self.now, monotonic=lambda: self.now,
                                                    processes=self.processes, ports=Ports())
        self.supervisor._descriptor_healthy = lambda lease, now: True
        self.rows = []
        self.supervisor.load_desired = lambda: sorted(self.rows, key=lambda value: value.instance_id)

    def step(self, rows, advance=1.0):
        self.now += advance
        self.rows = rows
        return self.supervisor.step()

    def kinds(self, actions, kind):
        return [action["instance_id"] for action in actions if action["action"] == kind]

    def test_queued_demand_evicts_least_recent_empty_personal_world_before_warm_nexus(self):
        nexus, home_a, home_b = "pub-" + "1" * 32, "apt-" + "a" * 32, "apt-" + "b" * 32
        self.assertEqual(self.kinds(self.step([row(nexus, "public", 1), row(home_a, demands=1)]), "launch"),
                         [home_a, nexus])
        self.step([row(nexus, "public"), row(home_a)])  # Both empty: warm in grace, not stopped yet.
        actions = self.step([row(nexus, "public"), row(home_a), row(home_b, demands=1)])
        self.assertEqual(self.kinds(actions, "queue"), [home_b])
        self.assertEqual(self.kinds(actions, "evict"), [home_a])
        self.assertIn(nexus, self.supervisor.children)
        actions = self.step([row(nexus, "public"), row(home_a), row(home_b, demands=1)])
        self.assertEqual(self.kinds(actions, "launch"), [home_b])
        self.assertEqual(self.supervisor.leases[home_a].state, "evicted")
        # Still idle: an evicted world is never relaunched without demand.
        self.assertEqual(self.kinds(self.step([row(nexus, "public"), row(home_a), row(home_b, demands=1)]),
                                    "launch"), [])

    def test_warm_nexus_is_evicted_only_for_a_player_demand(self):
        nexus, home_a, home_b = "pub-" + "1" * 32, "apt-" + "a" * 32, "apt-" + "b" * 32
        self.step([row(nexus, "public", 1), row(home_a, demands=1)])
        self.assertEqual(self.kinds(self.step([row(nexus, "public"), row(home_a, allocations=1)]), "evict"), [])
        actions = self.step([row(nexus, "public"), row(home_a, allocations=1), row(home_b, demands=1)])
        self.assertEqual((self.kinds(actions, "evict"), self.kinds(actions, "queue")), ([nexus], [home_b]))

    def test_occupied_worlds_are_never_evicted_and_draining_slots_are_credited(self):
        nexus, home_a, home_b, home_c = ("pub-" + "1" * 32, "apt-" + "a" * 32, "apt-" + "b" * 32,
                                         "apt-" + "c" * 32)
        self.step([row(nexus, "public", allocations=3), row(home_a, allocations=1)])
        actions = self.step([row(nexus, "public", allocations=3), row(home_a, allocations=1),
                             row(home_b, demands=1)])
        self.assertEqual((self.kinds(actions, "queue"), self.kinds(actions, "evict")), ([home_b], []))
        self.assertFalse(any(child.terminated for _, child in self.processes.spawned))
        # One empty world, two queued demands: exactly one eviction, then no repeat while draining.
        rows = [row(nexus, "public", allocations=3), row(home_a), row(home_b, demands=1), row(home_c, demands=1)]
        self.supervisor.children[home_a].terminate = lambda: None  # Slow to exit.
        self.assertEqual(self.kinds(self.step(rows), "evict"), [home_a])
        self.assertEqual(self.kinds(self.step(rows), "evict"), [])

    def test_public_and_personal_idle_ttls_are_separate(self):
        nexus, home = "pub-" + "1" * 32, "apt-" + "a" * 32
        self.step([row(nexus, "public", 1), row(home, demands=1)])
        self.step([row(nexus, "public"), row(home)])
        actions = self.step([row(nexus, "public"), row(home)], advance=61)
        self.assertEqual([(action["instance_id"], action["reason"]) for action in actions
                          if action["action"] == "stop"], [(home, "idle TTL")])
        actions = self.step([row(nexus, "public"), row(home)], advance=840)
        self.assertEqual([action["instance_id"] for action in actions if action["action"] == "stop"], [nexus])


class EntrypointIdlePolicy(unittest.TestCase):
    def test_supervisor_receives_personal_and_public_idle_ttls(self):
        spec = importlib.util.spec_from_file_location("capacity_entrypoint", BACKEND.parent / "deployment/docker/entrypoint.py")
        entrypoint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entrypoint)
        pins = {key: "0" * 64 for key in ("NEBULA_BUILD_REPORT_SHA256", "NEBULA_SERVER_SHA256", "NEBULA_MANAGED_SHA256")}
        _, supervisor, _ = entrypoint.plan(pins)
        self.assertEqual((supervisor[supervisor.index("--idle-ttl") + 1],
                          supervisor[supervisor.index("--public-idle-ttl") + 1]), ("60.0", "900.0"))
        _, supervisor, _ = entrypoint.plan({**pins, "NEBULA_IDLE_TTL": "30", "NEBULA_PUBLIC_WORLD_IDLE_SECONDS": "120",
                                            "NEBULA_MAX_PROCESSES": "4"})
        self.assertEqual(supervisor[supervisor.index("--max-processes") + 1], "4")
        self.assertEqual((supervisor[supervisor.index("--idle-ttl") + 1],
                          supervisor[supervisor.index("--public-idle-ttl") + 1]), ("30.0", "120.0"))
        args = SUPERVISOR.parse_args(supervisor[2:])
        self.assertEqual((args.idle_ttl, args.public_idle_ttl), (30.0, 120.0))
        with self.assertRaises(ValueError):
            entrypoint.plan({**pins, "NEBULA_PUBLIC_WORLD_IDLE_SECONDS": "-5"})


if __name__ == "__main__": unittest.main()
