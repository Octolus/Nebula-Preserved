"""Offline registry files only. Never starts or connects to an instance."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from allocation import InstanceDirectory
from wire import ProtocolError


class Allocation(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, 'socket', side_effect=AssertionError('No sockets in offline checks'))
        self.guard.start()
        scratch = (Path(tempfile.gettempdir()) / "nebula-preserved-tests") / 'work/offline-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.directory = InstanceDirectory(self.root)

    def tearDown(self):
        self.temp.cleanup()
        self.guard.stop()

    def descriptor(self, instance='nexus-a', space='Nexus', port=28000, players=0, legacy=False, **overrides):
        value = dict(format_version=1, protocol_complete=True, listening=True, heartbeat=time.time(),
                     ip='127.0.0.1', port=port, instance_id=instance, psidglobal=space, players=players, maxusers=32)
        value.update(overrides)
        path = self.root / 'instance-status.json' if legacy else self.root / 'instances' / instance / 'instance-status.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_select_space_target_and_alternative(self):
        self.descriptor(players=7)
        self.descriptor('nexus-b', port=28001, players=2)
        self.descriptor('leafpark-a', 'LeafPark', 28002, 1)
        self.assertEqual(self.directory.require('Nexus')['instance_id'], 'nexus-b')
        self.assertEqual(self.directory.require('Nexus', exclude_instance='nexus-b')['instance_id'], 'nexus-a')
        self.assertEqual(self.directory.require('LeafPark')['port'], 28002)
        self.assertIsNone(self.directory.ready('Nexus', instance_id='leafpark-a'))
        with self.assertRaises(ProtocolError): self.directory.require('MissingSpace')

    def test_stale_incomplete_external_and_future_never_select(self):
        self.descriptor('stale', heartbeat=time.time()-16)
        self.descriptor('incomplete', port=28001, protocol_complete=False)
        self.descriptor('external', port=28002, ip='192.0.2.1')
        self.descriptor('future', port=28003, heartbeat=time.time()+60)
        self.assertEqual(self.directory.all_ready(), [])

    def test_ambiguous_ids_and_ports_fail_closed(self):
        self.descriptor(legacy=True)
        self.descriptor(port=28001)
        self.assertEqual(self.directory.all_ready(), [])
        self.descriptor('other', port=28000)
        self.assertEqual(self.directory.all_ready(), [])

    def test_invalid_numeric_types_and_folder_mismatch(self):
        self.descriptor('fraction', port=28000.5)
        self.descriptor('bool', port=28001, players=True)
        path = self.descriptor('wrong-folder', port=28002)
        value = json.loads(path.read_text()); value['instance_id'] = 'other-id'
        path.write_text(json.dumps(value))
        self.assertEqual(self.directory.all_ready(), [])

    def test_legacy_bom_and_full_instance_remain_representable(self):
        path = self.descriptor(players=32, legacy=True)
        path.write_text(path.read_text(), encoding='utf-8-sig')
        self.assertEqual(self.directory.require()['players'], 32)
        self.assertIsNone(self.directory.ready(exclude_instance='nexus-a'))

    def test_malformed_descriptor_does_not_hide_valid_other_space(self):
        path = self.descriptor()
        path.write_text('{incomplete-json')
        self.descriptor('leafpark', 'LeafPark', port=28001)
        self.assertEqual([x['instance_id'] for x in self.directory.all_ready()], ['leafpark'])

    def test_explicit_shared_server_advertisement_admits_only_its_exact_address(self):
        shared = InstanceDirectory(self.root, advertised_ip='192.0.2.10')
        self.descriptor('shared', ip='192.0.2.10', bind='0.0.0.0', game_ready=True)
        self.descriptor('unexpected', port=28001, ip='192.0.2.11', bind='0.0.0.0')
        self.descriptor('loopback', port=28002)
        self.assertEqual([x['instance_id'] for x in shared.all_ready()], ['shared'])
        self.assertEqual(shared.require('Nexus')['ip'], '192.0.2.10')
        self.assertEqual([x['instance_id'] for x in self.directory.all_ready()], ['loopback'])

    def test_shared_advertisement_does_not_override_any_readiness_gate(self):
        shared = InstanceDirectory(self.root, advertised_ip='10.23.4.5')
        self.descriptor('incomplete', ip='10.23.4.5', protocol_complete=False)
        self.descriptor('not-listening', port=28001, ip='10.23.4.5', listening=False)
        self.descriptor('not-game-ready', port=28002, ip='10.23.4.5', game_ready=False)
        self.descriptor('numeric-game-ready', port=28003, ip='10.23.4.5', game_ready=1)
        self.descriptor('stale', port=28004, ip='10.23.4.5', heartbeat=time.time()-16)
        self.assertEqual(shared.all_ready(), [])
        with self.assertRaises(ProtocolError): shared.require()

    def test_invalid_shared_descriptors_never_become_redirect_destinations(self):
        shared = InstanceDirectory(self.root, advertised_ip='192.0.2.10')
        invalid = [('wildcard','0.0.0.0',28000,'0.0.0.0'),
                   ('hostname','example.test',28001,'0.0.0.0'),
                   ('legacy-ip','192.000.2.10',28002,'0.0.0.0'),
                   ('ipv6','::1',28003,'0.0.0.0'),
                   ('bad-port','192.0.2.10',True,'0.0.0.0'),
                   ('text-port','192.0.2.10','28005','0.0.0.0'),
                   ('bad-bind','192.0.2.10',28006,'224.0.0.1')]
        for name,ip,port,bind in invalid:
            self.descriptor(name,ip=ip,port=port,bind=bind)
        self.assertEqual(shared.all_ready(), [])

    def test_invalid_config_is_rejected_and_cannot_replace_existing_allowlist(self):
        for address in ('0.0.0.0','0.0.0.1','224.0.0.1','255.255.255.255','localhost','::1','127.1',None,1,True):
            with self.subTest(address=address):
                with self.assertRaises(ValueError): InstanceDirectory(self.root, advertised_ip=address)
                with self.assertRaises(ValueError): self.directory.advertised_ip = address
                self.assertEqual(self.directory.advertised_ip,'127.0.0.1')


if __name__ == '__main__': unittest.main()

