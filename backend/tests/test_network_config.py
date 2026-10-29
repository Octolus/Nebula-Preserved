"""Pure shared-host address/config tests. No listener or socket may start."""
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from allocation import ipv4_address, network_port
import server


class NetworkConfig(unittest.TestCase):
    def setUp(self):
        self.no_socket=patch.object(socket,'socket',side_effect=AssertionError('Sockets forbidden in config checks'))
        self.no_socket.start()

    def tearDown(self):
        self.no_socket.stop()

    def test_defaults_preserve_loopback_and_no_automatic_listen(self):
        args=server.parse_args([])
        self.assertEqual((args.bind,args.advertise_ip,args.port,args.listen),('127.0.0.1','127.0.0.1',8080,False))

    def test_wildcard_listen_is_separate_from_concrete_advertisement(self):
        args=server.parse_args(['--bind','0.0.0.0','--advertise-ip','192.0.2.10','--port','8081'])
        self.assertEqual((args.bind,args.advertise_ip,args.port),('0.0.0.0','192.0.2.10',8081))
        self.assertFalse(args.listen)
        self.assertEqual(ipv4_address('10.1.2.3'),'10.1.2.3')
        self.assertEqual(ipv4_address('203.0.113.7'),'203.0.113.7')

    def test_invalid_address_forms_and_nonunicast_advertisements_fail(self):
        invalid=['','localhost','https://192.0.2.1','192.0.2.1:28000','127.1','2130706433',
                 '127.00.0.1','0x7f.0.0.1',' 127.0.0.1','127.0.0.1 ','::1','::ffff:127.0.0.1',
                 '0.0.0.0','0.0.0.1','224.0.0.1','240.0.0.1','255.255.255.255',None,True,1]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): ipv4_address(value)
        self.assertEqual(ipv4_address('0.0.0.0',wildcard=True),'0.0.0.0')
        for value in ('0.0.0.1','224.0.0.1','::','localhost'):
            with self.assertRaises(ValueError): ipv4_address(value,wildcard=True)

    def test_ports_are_exact_integers_and_cli_rejects_invalid_network_config(self):
        for value in (0,-1,65536,True,8080.0,'8080',None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): network_port(value)
        self.assertEqual(network_port(1),1)
        self.assertEqual(network_port(65535),65535)
        for argv in (['--bind','::'],['--advertise-ip','0.0.0.0'],['--port','0'],['--port','65536']):
            with self.subTest(argv=argv),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error: server.parse_args(argv)
                self.assertEqual(error.exception.code,2)

    def test_backend_configures_same_allocator_object_without_disturbing_state_refresh(self):
        scratch=(Path(tempfile.gettempdir()) / "nebula-preserved-tests")/'work/offline-network-config-tests'
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            backend=server.Backend(Path(directory),bind='0.0.0.0',advertise_ip='192.0.2.10',port=8081)
            try:
                self.assertEqual(backend.bind_address,'0.0.0.0')
                self.assertEqual(backend.service.instances.advertised_ip,'192.0.2.10')
                self.assertIs(backend.service.instances,backend.service.rewards.instances)
                self.assertIsNone(backend.maintenance_task)
                backend.publish_state()
                state=Path(directory)
                for filename in ('instance-accounts.json','instance-relations.json','instance-notifications.json'):
                    self.assertEqual(json.loads((state/filename).read_text())['format_version'],1)
            finally:
                backend.log.close()
                backend.store.close()

    def test_invalid_backend_config_has_no_filesystem_side_effects(self):
        scratch=(Path(tempfile.gettempdir()) / "nebula-preserved-tests")/'work/offline-network-config-tests'
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            state=Path(directory)/'never-created'
            with self.assertRaises(ValueError): server.Backend(state,advertise_ip='0.0.0.0')
            self.assertFalse(state.exists())


if __name__=='__main__': unittest.main()

