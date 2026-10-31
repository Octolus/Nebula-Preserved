"""Native initialization ordering tests for the authenticated TLS gateway."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import remote_gateway as gateway
from wire import encrypt


GUID = "actor-session-guid"
OTHER_GUID = "different-session-guid"
TIMESTAMP = struct.pack("<d", 123.5)


def message(plaintext):
    ciphertext = encrypt(plaintext).encode("ascii")
    return struct.pack("<HH", gateway.NEBULA, len(ciphertext) + 1) + ciphertext


def batch(*messages):
    return TIMESTAMP + b"".join(messages)


def ready():
    return struct.pack("<H", gateway.READY)


def ping(value=1.25):
    return struct.pack("<Hd", gateway.PING, value)


def early_occupable(guid=GUID):
    return message(f"8#{guid}#17#StandaloneWindows")


def early_animation(guid=GUID):
    return message(f"4#{guid}#31#0#0#Idle#0##StandaloneWindows")


def early_registry(guid=GUID):
    return message(f"97#{guid}#42#0#1#e30#StandaloneWindows")


class GatewayInitializationTests(unittest.TestCase):
    def accepted(self, application):
        original = batch(application)
        outputs, bound = gateway.first_identity_frame(original, GUID)
        self.assertTrue(bound)
        self.assertEqual(outputs, [original])

    def test_native_preannouncement_occupable_binds_actor(self):
        self.accepted(early_occupable())

    def test_native_preannouncement_animation_binds_actor(self):
        self.accepted(early_animation())

    def test_native_preannouncement_registry_chunk_binds_actor(self):
        self.accepted(early_registry())

    def test_guidless_updates_before_binding_are_forwarded_unbound(self):
        # The scene keeps the latest pre-binding speed/transform and applies it
        # on binding (NebulaInstanceServer.ApplyPreBinding); 19/30 are still
        # rejected there until bound. The gateway must not drop them.
        packets = (
            message('2#31#{"position":{"x":0,"y":0,"z":0}}#StandaloneWindows'),
            message("19#source#target#1#0#StandaloneWindows"),
            message("30#True#StandaloneWindows"),
        )
        for packet in packets:
            with self.subTest(packet=packet[:4]):
                original = batch(packet)
                outputs, bound = gateway.first_identity_frame(original, GUID)
                self.assertFalse(bound)
                self.assertEqual(outputs, [original])

    def test_preannouncement_mirror_command_is_forwarded_unbound(self):
        # [Command] SetSpeed(float): netId, component 1, hash, payload size+1.
        speed = (struct.pack("<HIBi", gateway.COMMAND, 31, 1, 421014902) +
                 struct.pack("<I", 5) + struct.pack("<f", 2.5))
        original = batch(ready(), speed)
        outputs, bound = gateway.first_identity_frame(original, GUID)
        self.assertFalse(bound)
        self.assertEqual(outputs, [original])

    def test_guidless_frames_never_bind_or_relax_the_actor_check(self):
        transform = message('2#31#{"position":{"x":0,"y":0,"z":0}}#StandaloneWindows')
        _, bound = gateway.first_identity_frame(batch(transform), GUID)
        self.assertFalse(bound)
        with self.assertRaises(gateway.Denied) as raised:
            gateway.first_identity_frame(batch(transform, early_occupable(OTHER_GUID)), GUID)
        self.assertEqual(raised.exception.args, ("application_identity",))

    def test_mixed_batch_is_forwarded_whole_and_in_order(self):
        control = ready() + ping()
        early = message("30#True#StandaloneWindows")
        binding = early_occupable()
        after_binding = early_animation()
        original = batch(control, early, binding, after_binding)
        outputs, bound = gateway.first_identity_frame(original, GUID)
        self.assertTrue(bound)
        self.assertEqual(outputs, [original])

    def test_timestamp_only_batch_forwards_nothing(self):
        self.assertEqual(gateway.first_identity_frame(TIMESTAMP, GUID), ([], False))

    def test_guidless_request_after_same_batch_binding_is_forwarded(self):
        binding = early_registry()
        day_night = message("30#False#StandaloneWindows")
        outputs, bound = gateway.first_identity_frame(batch(binding, day_night), GUID)
        self.assertTrue(bound)
        self.assertEqual(outputs, [batch(binding, day_night)])

    def test_every_preannouncement_guid_bearing_request_rejects_other_actor(self):
        for packet in (early_occupable(OTHER_GUID), early_animation(OTHER_GUID),
                       early_registry(OTHER_GUID)):
            with self.subTest(packet=packet[:4]), self.assertRaises(gateway.Denied) as raised:
                gateway.first_identity_frame(batch(packet), GUID)
            self.assertEqual(raised.exception.args, ("application_identity",))

    def test_opcode_one_retains_exact_schema_and_actor_checks(self):
        valid = message(f"1#31#{GUID}#Player#0#StandaloneWindows")
        self.accepted(valid)
        invalid = (
            message(f"1#31#{OTHER_GUID}#Player#0#StandaloneWindows"),
            message(f"1#31#{GUID}#Player#StandaloneWindows"),
            message(f"1#31#{GUID}#Player#0#extra#StandaloneWindows"),
        )
        for packet in invalid:
            with self.subTest(packet=packet[:4]), self.assertRaises(gateway.Denied) as raised:
                gateway.first_identity_frame(batch(packet), GUID)
            self.assertEqual(raised.exception.args, ("application_identity",))


if __name__ == "__main__":
    unittest.main()
