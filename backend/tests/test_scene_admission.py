"""N2LoadSpace destination coverage: every original destination is admitted or has an exact blocker.

Offline only: no sockets, game, listener or supervisor process.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import unittest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from allocation import NONMINI_PUBLIC_SCENES, NONMINI_SEMANTIC_PERSONAL_SCENES
from housing import PERSONAL_SPACE_SCENES
from interaction_registry import InteractionRegistryPublisher
from wire import ProtocolError
import test_contracts as contracts
import test_instance_lifecycle as fixture

# Shipped client destinations that reach NETGcloudLogin.LoadSpace (0x3d5a40):
# - PreInitLOAD.NavigatorPublicSpaces in s/preinitiload (PublicSpacesDisabled is
#   empty); NavigatorSelector.OnOpenScene (0x47d130) sends NavigatorItem.scene_name.
# - CustomSpaceTrigger/CinemaSpaceTrigger.spaceName in s/nexuslogicprefab
#   (Interact 0x44e840/0x44e800): GhostTown, Cube, ZeroDistrict, Beach, Dome,
#   LeafPark, Bowling and StoneLakeCastle are active; SteamPunk, Cinema and SKL
#   triggers are shipped inactive. ZeroDistrict also links to Cube; every other
#   world links back to Nexus.
# - The personal navigator (http-nonminigame-gap-audit.json) and the friend
#   invite, which loads the friend's psidglobal with its session GUID.
NAVIGATOR_PUBLIC = ("Nexus", "Bowling", "Dome", "StoneLakeCastle", "Beach", "Cube", "LeafPark",
                    "SteamPunk", "GhostTown", "TheNebulianOpenHouse", "ZeroDistrict",
                    "NebuHouseOpenHouse", "WestValleyApartmentOpenHouse", "MedievalVillage")
TRIGGER_ONLY_PUBLIC = ("Cinema", "SKL")
# Original public destinations the shipped client cannot load.
BLOCKED_PUBLIC = {
    # Only s/steampunklogicprefab ships; Scenes.Load needs s/steampunk.
    "SteamPunk": "client_scene_bundle_absent",
}


class DestinationCoverage(unittest.TestCase):
    def test_every_original_destination_is_admitted_or_has_an_exact_blocker(self):
        audit = json.loads((ROOT / "protocol/http-nonminigame-gap-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(set(audit["personal_space_navigator_names"]), set(PERSONAL_SPACE_SCENES))
        original_public = set(NAVIGATOR_PUBLIC) | set(TRIGGER_ONLY_PUBLIC)
        self.assertEqual(original_public, NONMINI_PUBLIC_SCENES | set(BLOCKED_PUBLIC))
        self.assertFalse(NONMINI_PUBLIC_SCENES & set(BLOCKED_PUBLIC))
        self.assertEqual(set(PERSONAL_SPACE_SCENES.values()), set(NONMINI_SEMANTIC_PERSONAL_SCENES))

    def test_every_admitted_scene_has_a_complete_static_registry(self):
        publisher = InteractionRegistryPublisher(None, ROOT / "protocol")
        self.assertEqual(publisher.PUBLIC_SCENES, NONMINI_PUBLIC_SCENES)
        for scene in NONMINI_PUBLIC_SCENES | NONMINI_SEMANTIC_PERSONAL_SCENES:
            with self.subTest(scene=scene):
                self.assertTrue(publisher.scene_profiles[scene]["available"])
        # Blocked scenes would otherwise publish an untrusted registry.
        self.assertFalse(set(BLOCKED_PUBLIC) & set(publisher.scene_profiles))

    def test_supervisor_allow_lists_match_backend_and_scene_server(self):
        admitted = NONMINI_PUBLIC_SCENES | NONMINI_SEMANTIC_PERSONAL_SCENES
        spec = importlib.util.spec_from_file_location(
            "scene_admission_entrypoint", ROOT / "deployment/docker/entrypoint.py")
        entrypoint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entrypoint)  # no import-time process or listener
        self.assertEqual(len(entrypoint.SCENES), len(set(entrypoint.SCENES)))
        self.assertEqual(set(entrypoint.SCENES), admitted)
        unit = (ROOT / "deployment/instance-supervisor/nebula-instance-supervisor.service").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"--allowed-scene (\S+)", unit)), admitted)
        readiness = (ROOT / "mirror-server/UnityProject/Assets/Preservation/NebulaCoreReadiness.cs").read_text(encoding="utf-8")
        public = re.search(r"publicScenes = \{([^}]*)\}", readiness).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)"', public)), NONMINI_PUBLIC_SCENES)


class ManagedDestinations(unittest.TestCase):
    setUp = fixture.ManagedInstanceTests.setUp
    tearDown = fixture.ManagedInstanceTests.tearDown
    account = fixture.ManagedInstanceTests.account
    descriptor = fixture.ManagedInstanceTests.descriptor
    presence = fixture.ManagedInstanceTests.presence
    load = fixture.ManagedInstanceTests.load
    poll = fixture.ManagedInstanceTests.poll

    def demand(self, guid):
        return self.store.db.execute(
            "SELECT instance_id,desired_owner_guid FROM instance_demands WHERE requester_guid=?", (guid,)).fetchone()

    def friend_in(self, scene, instance_id, players=1):
        friend = self.account("friend")
        self.descriptor(instance_id, scene, players=players)
        self.assertEqual(self.load(friend, "friend", scene), friend + "#false#false")
        self.assertEqual(self.poll(friend, "friend").split("#")[2], instance_id)
        self.presence(instance_id, scene, [friend])
        return friend

    def test_blocked_destinations_fail_before_reserving_a_world(self):
        guid = self.account("traveller")
        for scene in sorted(BLOCKED_PUBLIC):
            with self.subTest(scene=scene), self.assertRaises(ProtocolError) as raised:
                self.load(guid, "traveller", scene)
            self.assertEqual(raised.exception.status, 404)
        self.assertIsNone(self.demand(guid))
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM managed_instances WHERE kind='public'").fetchone()[0], 0)

    def test_every_admitted_public_scene_reserves_its_exact_scene(self):
        for scene in sorted(NONMINI_PUBLIC_SCENES):
            with self.subTest(scene=scene):
                guid = self.account("visitor-" + scene.lower())
                self.assertEqual(self.load(guid, "visitor-" + scene.lower(), scene), guid + "#false#false")
                row = self.store.db.execute(
                    "SELECT m.kind,m.psidglobal FROM instance_demands d JOIN managed_instances m "
                    "USING(instance_id) WHERE d.requester_guid=?", (guid,)).fetchone()
                self.assertEqual(tuple(row), ("public", scene))

    def test_every_admitted_public_scene_becomes_ready_with_its_registry(self):
        for port, scene in enumerate(sorted(NONMINI_PUBLIC_SCENES), 28001):
            with self.subTest(scene=scene):
                instance_id = "world-" + scene.lower()
                self.descriptor(instance_id, scene, port=port)  # also publishes the registry
                guid = self.account("arrival-" + scene.lower())
                self.assertEqual(self.load(guid, "arrival-" + scene.lower(), scene), guid + "#false#false")
                self.assertEqual(self.poll(guid, "arrival-" + scene.lower()).split("#")[1:4],
                                 ["true", instance_id, scene])

    def test_invite_joins_friend_in_exact_shared_world(self):
        friend = self.friend_in("LeafPark", "busy-leafpark", players=5)
        # A quieter instance of the same scene would win ordinary selection.
        self.descriptor("quiet-leafpark", "LeafPark", players=0, port=28002)
        # Native InviteToJoin: psidglobal and GUID come from this lookup.
        joiner = self.account("joiner")
        self.assertEqual(self.service.dispatch("N2GetPsidglobalAndGuidByUsernamePlatform", "#".join(
            (joiner, "friend", "1", "StandaloneWindows"))), "OK#LeafPark#" + friend)
        self.assertEqual(self.load(joiner, "joiner", "LeafPark", friend), joiner + "#false#false")
        self.assertEqual(tuple(self.demand(joiner)), ("busy-leafpark", friend))
        self.assertEqual(self.poll(joiner, "joiner").split("#")[1:4], ["true", "busy-leafpark", "LeafPark"])
        # The pinned demand survives the friend moving on; shared worlds carry no owner authority.
        self.presence("busy-leafpark", "LeafPark", [joiner])
        self.assertEqual(self.poll(joiner, "joiner").split("#")[2], "busy-leafpark")

    def test_invite_to_full_shared_world_uses_native_no_free_slot(self):
        friend = self.friend_in("Nexus", "full-nexus")
        self.descriptor("full-nexus", "Nexus", players=32)
        joiner = self.account("late-joiner")
        self.assertEqual(self.load(joiner, "late-joiner", "Nexus", friend), joiner + "#false#true")
        self.assertIsNone(self.demand(joiner))

    def test_invite_requires_present_current_friend_in_requested_world(self):
        friend = self.friend_in("Beach", "beach-a")
        joiner = self.account("strict-joiner")
        for scene, exclude in (("Nexus", ""), ("Beach", "beach-a")):
            with self.subTest(scene=scene, exclude=exclude), self.assertRaises(ProtocolError) as raised:
                self.load(joiner, "strict-joiner", scene, friend, exclude)
            self.assertEqual(raised.exception.status, 503)
        with self.assertRaises(ProtocolError) as raised:
            self.load(joiner, "strict-joiner", "Home", friend)  # apartment authority still applies
        self.assertEqual(raised.exception.status, 403)
        self.presence("beach-a", "Beach", [])
        with self.assertRaises(ProtocolError) as raised:
            self.load(joiner, "strict-joiner", "Beach", friend)
        self.assertEqual(raised.exception.status, 503)
        self.assertIsNone(self.demand(joiner))


class ManualDestinations(unittest.TestCase):
    setUpClass = classmethod(contracts.Contracts.setUpClass.__func__)
    setUp = contracts.Contracts.setUp
    tearDown = contracts.Contracts.tearDown
    call = contracts.Contracts.call
    login = contracts.Contracts.login

    def instance(self, instance_id, scene, port, players):
        value = {"format_version": 1, "protocol_complete": True, "listening": True,
                 "heartbeat": time.time(), "ip": "127.0.0.1", "port": port,
                 "instance_id": instance_id, "psidglobal": scene, "maxusers": 32, "players": players}
        folder = self.path / "instances" / instance_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "instance-status.json").write_text(json.dumps(value), encoding="utf-8")

    def test_invite_joins_friend_instance_not_least_populated(self):
        self.instance("nexus-busy", "Nexus", 28001, 7)
        self.instance("nexus-quiet", "Nexus", 28002, 0)
        friend = self.login("offline-account-b", "Friend")
        self.call("N2LoadSpace", friend, "offline-account-b", "Nexus", "false", "nexus-quiet", "")
        self.assertEqual(self.call("N2SpaceLoading", friend, "offline-account-b").split("#")[2], "nexus-busy")
        (self.path / "instances/nexus-busy/instance-presence.json").write_text(json.dumps({
            "format_version": 1, "generation": time.time(), "instance_id": "nexus-busy",
            "psidglobal": "Nexus", "players": [{"guid": friend, "status": 0}]}), encoding="utf-8")
        self.assertEqual(self.call("N2GetPsidglobalAndGuidByUsernamePlatform", self.guid, "Friend", "1"),
                         "OK#Nexus#" + friend)
        self.assertEqual(self.call("N2LoadSpace", self.guid, "offline-account-a", "Nexus", "true", "", friend),
                         self.guid + "#false#false")
        self.assertEqual(self.call("N2SpaceLoading", self.guid, "offline-account-a").split("#")[2:4],
                         ["nexus-busy", "Nexus"])


if __name__ == "__main__":
    unittest.main()
