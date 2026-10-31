"""Reviewed scenes and fresh independent ownership are required for apartments."""
import json
import re
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from allocation import (InstanceDirectory, MINIGAME_SCENE_TABLES, NONMINI_PERSONAL_SCENES, NONMINI_PUBLIC_SCENES,
                        NONMINI_SEMANTIC_PERSONAL_SCENES, validation_profile)
from service import Service
from state import Store, Catalog
from wire import ProtocolError
import server


class NonminiReadiness(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, 'socket', side_effect=AssertionError('Sockets forbidden'))
        self.guard.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests")/'work/offline-nonmini-readiness'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.directory = InstanceDirectory(self.root, core_test_profile='nonmini-core-v1')

    def tearDown(self):
        self.temp.cleanup()
        self.guard.stop()

    def descriptor(self, scene='Home', **overrides):
        personal = scene in NONMINI_PERSONAL_SCENES
        value = dict(format_version=1, protocol_complete=False, game_ready=False, networking_parity='unproven',
            listening=True, listener_bound=True, readiness_scope='nonmini-core-v1', core_test_eligible=True,
            board_tables=0, darts_tables=0, heartbeat=time.time(), ip='127.0.0.1', bind='127.0.0.1',
            port=28002, instance_id='apartment-test', psidglobal=scene, players=0, maxusers=32,
            scene_registry_verified=True, housing_bound=personal, housing_owner='owner' if personal else '')
        value.update(MINIGAME_SCENE_TABLES.get(scene, {}))
        value.update(overrides)
        path=self.root/'instances/apartment-test/instance-status.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')

    def binding(self, **overrides):
        binding=dict(instance_id='apartment-test', psidglobal='Home', owner_ps4_id='owner',logical_space_key='Home')
        binding.update(overrides)
        value=dict(format_version=1,generation=time.time(),bindings=[binding])
        (self.root/'instance-housing.json').write_text(json.dumps(value),encoding='utf-8')
        return value

    def semantic_registry(self, scene_name, count, ordinary, deferred, **overrides):
        entries=[dict(classification='ordinary') for _ in range(ordinary)]
        entries += [dict(classification='deferred_minigame') for _ in range(deferred)]
        entries += [dict(classification='invalid') for _ in range(count-len(entries))]
        row=dict(instance_id='apartment-test',scene=scene_name,trusted=True,static_profile_available=True,
                 epoch='e',static_entries=entries,furniture_entries=[],ground_sig=[])
        row.update(overrides)
        value=dict(format_version=1,generation=time.time(),instances=[row])
        (self.root/'instance-interactions.json').write_text(json.dumps(value),encoding='utf-8')
        return value

    def test_public_and_personal_scope_keep_full_readiness_false(self):
        self.assertEqual(validation_profile('nonmini-core-v1'),'nonmini-core-v1')
        self.assertEqual(server.parse_args(['--core-test-profile','nonmini-core-v1']).core_test_profile,'nonmini-core-v1')
        for scene in NONMINI_PUBLIC_SCENES:
            self.descriptor(scene)
            self.assertIsNotNone(self.directory.ready(scene))
            self.assertIsNone(InstanceDirectory(self.root).ready(scene))
            self.assertIsNone(InstanceDirectory(self.root,core_test_profile='nexus-core-v1').ready(scene))
        for scene in NONMINI_PERSONAL_SCENES:
            self.descriptor(scene)
            self.binding(psidglobal=scene,logical_space_key=scene)
            result=self.directory.require(scene)
            self.assertFalse(result['game_ready'])
            self.assertFalse(result['protocol_complete'])

    def test_descriptor_claim_alone_never_grants_apartment_readiness(self):
        self.descriptor()
        self.assertIsNone(self.directory.ready())
        for overrides in ({'owner_ps4_id':'someone-else'}, {'psidglobal':'CliffApartment'},
                          {'logical_space_key':'Unshipped'}, {'owner_ps4_id':''}):
            self.binding(**overrides)
            self.assertIsNone(self.directory.ready())
        value=self.binding()
        for invalid in ({'generation':time.time()-16}, {'generation':time.time()+60},
                        {'generation':True}, {'generation':'nan'}, {'format_version':True},
                        {'bindings':value['bindings']*2}, {'bindings':[None]}):
            (self.root/'instance-housing.json').write_text(json.dumps({**value,**invalid}))
            self.assertIsNone(self.directory.ready())
        self.binding()
        self.assertIsNotNone(self.directory.ready())

    def test_minigame_table_counts_must_match_the_shipped_scene(self):
        self.assertEqual(MINIGAME_SCENE_TABLES['StoneLakeCastle']['board_tables'], 8)
        self.assertEqual(MINIGAME_SCENE_TABLES['Bowling'],
                         {'board_tables': 0, 'darts_tables': 3, 'pool_tables': 9, 'bowling_lanes': 12})
        for scene in ('StoneLakeCastle', 'Bowling'):
            self.descriptor(scene)
            self.assertIsNotNone(self.directory.ready(scene))
        for scene, overrides in (('StoneLakeCastle', {'board_tables': 0}), ('StoneLakeCastle', {'board_tables': 7}),
                                 ('StoneLakeCastle', {'pool_tables': 9}), ('Bowling', {'bowling_lanes': 11}),
                                 ('Bowling', {'pool_tables': True}), ('Bowling', {'darts_tables': 0}),
                                 ('LeafPark', {'board_tables': 8}), ('LeafPark', {'bowling_lanes': 12}),
                                 ('Nexus', {'pool_tables': '0'})):
            with self.subTest(scene=scene, overrides=overrides):
                self.descriptor(scene, **overrides)
                self.assertIsNone(self.directory.ready(scene))
        # A runtime without the pool/bowling relay cannot serve Bowling.
        self.descriptor('Bowling')
        path = self.root/'instances/apartment-test/instance-status.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        del value['pool_tables'], value['bowling_lanes']
        path.write_text(json.dumps(value), encoding='utf-8')
        self.assertIsNone(self.directory.ready('Bowling'))

    def test_minigame_table_counts_match_the_scene_runtime_and_supervisor(self):
        source=(BACKEND.parent/'mirror-server/UnityProject/Assets/Preservation/NebulaCoreReadiness.cs').read_text()
        csharp={scene:tuple(map(int,counts.split(','))) for scene,counts in
                re.findall(r'if \(space == "(\w+)"\) return new\[\] \{ ([0-9, ]+) \};',source)}
        supervisor=(BACKEND.parent/'tools/instance_supervisor.py').read_text(encoding='utf-8')
        match=re.search(r'tables = \{(.*?)\}\.get\(',supervisor,re.S)
        self.assertIsNotNone(match)
        python_side={scene:tuple(map(int,counts.split(','))) for scene,counts in
                     re.findall(r'"(\w+)": \(([0-9, ]+)\)',match.group(1))}
        keys=('board_tables','darts_tables','pool_tables','bowling_lanes')
        expected={scene:tuple(row[k] for k in keys) for scene,row in MINIGAME_SCENE_TABLES.items()}
        self.assertEqual(csharp, expected)
        self.assertEqual(python_side, expected)

    def test_mixed_unknown_spelling_and_game_table_metadata_are_closed(self):
        self.binding()
        for scene in ('home','cube','SteamPunk','TokyoApartmentOpenHouse','CampSilverLake','CutteridgeEstate','SorcerersEyrie','Unknown'):
            self.descriptor(scene)
            self.assertIsNone(self.directory.ready())

    def test_mixed_scenes_require_semantic_process_and_complete_trusted_descriptor(self):
        directory=InstanceDirectory(self.root,core_test_profile='nonmini-semantic-v1')
        self.assertEqual(validation_profile('nonmini-semantic-v1'),'nonmini-semantic-v1')
        self.assertEqual(server.parse_args(['--core-test-profile','nonmini-semantic-v1']).core_test_profile,
                         'nonmini-semantic-v1')
        for scene,logical,total,ordinary,deferred in (
                ('CampSilverLake','CampSilverLake',9,8,1),
                ('CutteridgeEstate','CutteridgeEstate',5,4,1),
                ('SorcerersEyrie1','SorcerersEyrie',12,1,11)):
            self.descriptor(scene,readiness_scope='nonmini-semantic-v1',housing_bound=True,housing_owner='owner',
                            interaction_bridge_required=True,interaction_registry_trusted=True)
            self.binding(psidglobal=scene,logical_space_key=logical)
            self.semantic_registry(scene,total,ordinary,deferred)
            self.assertIsNotNone(directory.ready(scene))
            self.assertIsNone(self.directory.ready(scene))
            for bad in ({'trusted':False},{'static_profile_available':False},{'scene':'Home'},
                        {'static_entries':[dict(classification='ordinary')]}):
                self.semantic_registry(scene,total,ordinary,deferred,**bad)
                self.assertIsNone(directory.ready(scene))
            self.semantic_registry(scene,total,ordinary,deferred)
            self.descriptor(scene,readiness_scope='nonmini-semantic-v1',housing_bound=True,housing_owner='owner',
                            interaction_bridge_required=False,interaction_registry_trusted=True)
            self.assertIsNone(directory.ready(scene))
        for overrides in ({'scene_registry_verified':False},{'scene_registry_verified':1},
                          {'housing_bound':1},{'housing_owner':'other'}, {'board_tables':1},
                          {'darts_tables':True}, {'listener_bound':False}, {'readiness_scope':'nexus-core-v1'}):
            self.descriptor(**overrides)
            self.assertIsNone(self.directory.ready())

    def test_owner_and_invited_visitor_allocation_use_exact_binding(self):
        store=Store(self.root/'preservation.sqlite3')
        try:
            store.account('owner','Apartment Owner')
            store.account('visitor','Apartment Visitor')
            owner_guid, visitor_guid='a'*32,'b'*32
            store.bind_session('owner',owner_guid)
            store.bind_session('visitor',visitor_guid)
            service=Service(store,Catalog(BACKEND.parent/'protocol'))
            service.instances.core_test_profile='nonmini-core-v1'
            service.housing.bind_space('apartment-test','Home','owner')
            service.housing.export_bindings(self.root)
            self.descriptor()
            own='#'.join([owner_guid,'owner','Home','false','','','StandaloneWindows'])
            self.assertEqual(service.dispatch('N2LoadSpace',own),owner_guid+'#false#false')
            own_read='#'.join([owner_guid,'owner','Home','StandaloneWindows'])
            self.assertEqual(service.dispatch('HousingReadPresetServlet',own_read).split('#')[4],owner_guid)
            # Owner scene setup must work before the first presence heartbeat.
            self.assertEqual(store.presence(),{})
            uninvited='#'.join([visitor_guid,'visitor','Home','false','','','StandaloneWindows'])
            with self.assertRaises(ProtocolError): service.dispatch('N2LoadSpace',uninvited)
            visit='#'.join([visitor_guid,'visitor','Home','false','',owner_guid,'StandaloneWindows'])
            with self.assertRaises(ProtocolError): service.dispatch('N2LoadSpace',visit)
            presence=self.root/'instances/apartment-test/instance-presence.json'
            presence.write_text(json.dumps(dict(format_version=1,generation=time.time(),instance_id='apartment-test',
                psidglobal='Home',players=[dict(guid=owner_guid,status=0)])))
            self.assertEqual(service.dispatch('N2LoadSpace',visit),visitor_guid+'#false#false')
            fields=service.dispatch('N2SpaceLoading',visitor_guid+'#visitor#StandaloneWindows').split('#')
            self.assertEqual(fields,[visitor_guid,'true','apartment-test','Home','127.0.0.1','28002'])
            visitor_read='#'.join([visitor_guid,'visitor','Home','StandaloneWindows'])
            self.assertEqual(service.dispatch('HousingReadPresetServlet',visitor_read).split('#')[4],owner_guid)
            with self.assertRaises(ProtocolError):
                service.housing.save_part(visitor_guid,'Home','untrusted')
            # A fresh owner login in some other world cannot be advertised as
            # this apartment's owner. The old allocated GUID is historical.
            store.bind_session('owner','c'*32)
            for route,request in (('N2LoadSpace',visit),('HousingReadPresetServlet',visitor_read),
                                  ('HousingReadPresetServlet',own_read)):
                with self.assertRaises(ProtocolError): service.dispatch(route,request)
        finally:
            store.close()

    def test_both_language_scene_policies_match_exact_shipped_names(self):
        source=(BACKEND.parent/'mirror-server/UnityProject/Assets/Preservation/NebulaCoreReadiness.cs').read_text()
        def values(name):
            match=re.search(r'private static readonly string\[\] '+name+r' = \{(.*?)\};',source,re.S)
            self.assertIsNotNone(match)
            return re.findall(r'"([^"]+)"',match.group(1))
        personal=values('personal')
        public=values('publicScenes')
        shipped=json.loads((BACKEND.parent/'protocol/http-nonminigame-gap-audit.json').read_text())['personal_space_navigator_names']
        self.assertEqual(len(personal),len(set(personal)))
        self.assertEqual(set(personal),set(shipped))
        self.assertEqual(set(public),set(NONMINI_PUBLIC_SCENES))
        self.assertEqual(set(personal)-set(NONMINI_PERSONAL_SCENES),{'CampSilverLake','CutteridgeEstate','SorcerersEyrie'})
        self.assertEqual(set(NONMINI_SEMANTIC_PERSONAL_SCENES)-set(personal),{'SorcerersEyrie1'})


if __name__ == '__main__': unittest.main()

