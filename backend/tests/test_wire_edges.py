"""Pure original-frame boundaries and malformed ciphertext; no runtime needed."""
import base64
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from wire import KEY, ProtocolError, Request, decrypt, encrypt, json_field


class WireEdges(unittest.TestCase):
    def test_block_boundaries_and_multibyte_payloads_round_trip(self):
        for length in (0, 1, 15, 16, 17, 31, 32, 33, 255, 4096):
            for unit in ('a', '\u00e9', '\U0001f680', '#'):
                with self.subTest(length=length, unit=unit):
                    text = unit * length
                    self.assertEqual(decrypt(encrypt(text)), text)

    def test_malformed_base64_and_non_block_ciphertext_are_rejected(self):
        for payload in ('', '!', 'a', '====', 'AAAA', 'AA AA', 'AAAA\n'):
            with self.subTest(payload=repr(payload)), self.assertRaises(ValueError):
                decrypt(payload)

    def test_invalid_padding_and_non_utf8_plaintext_are_rejected(self):
        for raw in (b'\x00' * 16, pad(b'\xff', 16)):
            payload = base64.b64encode(AES.new(KEY, AES.MODE_ECB).encrypt(raw)).decode('ascii')
            with self.subTest(raw=raw.hex()), self.assertRaises(ValueError):
                decrypt(payload)

    def test_json_fields_preserve_delimiters_unicode_and_escaping_without_outer_split(self):
        values = ['', '#', '##', '\\u0023', 'quote"\\', '\n', '\U0001f680', '\u2028']
        for text in values:
            with self.subTest(text=repr(text)):
                field = json_field({'text': text, 'nested': [text, None, True, 0]})
                self.assertNotIn('#', field)
                self.assertEqual(json.loads(field), {'text': text, 'nested': [text, None, True, 0]})
                self.assertEqual(len(('prefix#' + field + '#suffix').split('#')), 3)

    def test_non_finite_json_numbers_cannot_escape_into_wire_frames(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                json_field({'nested': [value]})

    def test_platform_trailer_is_exact_and_only_the_final_token_is_authoritative(self):
        for text in ('', 'a', 'a#', 'a#Windows', 'a#PS4\n', 'a#ps4', 'a#StandaloneWindows#junk'):
            with self.subTest(text=repr(text)), self.assertRaises(ProtocolError):
                Request.parse(text)
        for platform in ('PS4', 'StandaloneWindows'):
            parsed = Request.parse('PS4##StandaloneWindows#' + platform)
            self.assertEqual(parsed.fields, ('PS4', '', 'StandaloneWindows'))
            self.assertEqual(parsed.platform, platform)

    def test_empty_fields_and_bounded_payload_splitting_are_preserved(self):
        self.assertEqual(Request.parse('#PS4').require(1), ('',))
        self.assertEqual(Request.parse('##PS4').require(2), ('', ''))
        request = Request.parse('guid#account#text#with#hashes#PS4', maxsplit=2)
        self.assertEqual(request.require(3), ('guid', 'account', 'text#with#hashes'))
        for count in (0, 1, 2, 4):
            with self.subTest(count=count), self.assertRaises(ProtocolError):
                request.require(count)
        self.assertEqual(request.require(3), ('guid', 'account', 'text#with#hashes'))


if __name__ == '__main__':
    unittest.main()
