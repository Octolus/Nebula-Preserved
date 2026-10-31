"""Native GET request lines carrying large saves must reach dispatch.

The client sends every HTTP command as UnityWebRequest.Get with the AES
payload in ?data= (Uri.EscapeDataString). Socket-free: the aiohttp request
parser is driven directly with the adapter's configured handler arguments.
"""
from pathlib import Path
import re
import sys
import unittest
import urllib.parse
from unittest import mock

from aiohttp.http_exceptions import LineTooLong
from aiohttp.http_parser import HttpRequestParser

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "tools"))

import server
from avatar import neutral, schema_fields
from avatar_entry_codec import encode_entry_fields, encode_value_texts
from housing import HOUSING_FIELDS
from wire import Request, decrypt, encrypt

GUID = "0123456789abcdef0123456789abcdef"
PS4ID = "76561198000000000"


def request_line(route, plaintext):
    # Uri.EscapeDataString leaves only RFC 3986 unreserved characters.
    data = urllib.parse.quote(encrypt(plaintext), safe="-_.~")
    return f"GET /{route}?data={data} HTTP/1.1\r\nHost: game\r\n\r\n".encode("ascii")


def full_preset_save(gender):
    """N2SavePreset with all 40 item slots equipped and full-precision floats."""
    preset, _assets, _position = neutral(ROOT / "protocol", PS4ID, gender)
    tokens = []
    for field in schema_fields(ROOT / "protocol", gender):
        value = preset.get(field["name"])
        if re.fullmatch(r"item\d+", field["name"]):
            value = "Q" * 32
        elif isinstance(value, float):
            value = value + 0.123456789
        tokens.append(None if value is None else str(value))
    numeric = "0" if gender == "MALE" else "1"
    return "#".join((GUID, PS4ID, "Preset name", numeric, encode_value_texts(tokens), "StandaloneWindows"))


def full_housing_part():
    """Part 0 of a layout at the recovered 200-item placement budget."""
    count = 200
    value = {
        "psidglobal": "LakeApartment",
        "aidasset": [f"A{i:031d}" if i < 100 else "null" for i in range(count)],
        "aidasset_tx": [f"{-17.123456 + i / 7:.6f}" if i < 100 else "0" for i in range(count)],
        "aidasset_ty": [f"{0.912345 + i / 97:.6f}" if i < 100 else "0" for i in range(count)],
        "aidasset_tz": [f"{12.654321 - i / 5:.6f}" if i < 100 else "0" for i in range(count)],
        "aidasset_r": [f"{(i * 37.5) % 360:.5f}" if i < 100 else "0" for i in range(count)],
        "aidassetWall": [f"W{i:031d}" for i in range(20)],
        "aidassetWallSlot": list(range(20)),
        "aidassetCeiling": [f"C{i:031d}" for i in range(10)],
        "aidassetCeilingSlot": list(range(10)),
        "atablename": None,
    }
    return "#".join((GUID, PS4ID, encode_entry_fields(value, HOUSING_FIELDS), "0", "StandaloneWindows"))


def parse(raw, **handler_args):
    parser = HttpRequestParser(mock.Mock(), mock.Mock(), 2 ** 16, **handler_args)
    messages, _upgraded, _tail = parser.feed_data(raw)
    return messages[0][0]


class RequestLineLimitTests(unittest.TestCase):
    def setUp(self):
        self.handler_args = server.application()._handler_args

    def test_adapter_configures_request_line_limit(self):
        self.assertEqual(self.handler_args, {"max_line_size": server.MAX_REQUEST_LINE})

    def test_limit_matches_fronting_nginx_buffers(self):
        for name in ("nginx-public.conf", "nginx-private.conf"):
            text = (ROOT / "deployment" / "docker" / name).read_text(encoding="utf-8")
            size = re.search(r"large_client_header_buffers\s+\d+\s+(\d+)k;", text)
            self.assertIsNotNone(size, name)
            self.assertEqual(int(size.group(1)) * 1024, server.MAX_REQUEST_LINE, name)

    def test_large_native_saves_exceed_default_but_reach_dispatch(self):
        cases = [("N2SavePreset", full_preset_save("MALE"), 4),
                 ("N2SavePreset", full_preset_save("FEMALE"), 4),
                 ("HousingSavePresetServletParts", full_housing_part(), -1)]
        for route, plaintext, maxsplit in cases:
            with self.subTest(route=route):
                raw = request_line(route, plaintext)
                self.assertGreater(len(raw), 8190)
                self.assertLess(len(raw), server.MAX_REQUEST_LINE)
                with self.assertRaises(LineTooLong):
                    parse(raw)  # aiohttp default: rejected with 400 before dispatch
                message = parse(raw, **self.handler_args)
                url = urllib.parse.urlsplit(message.path)
                self.assertEqual(url.path, "/" + route)
                data = urllib.parse.parse_qs(url.query)["data"][0]
                self.assertEqual(decrypt(data), plaintext)
                parsed = Request.parse(decrypt(data), maxsplit=maxsplit)
                self.assertEqual(parsed.platform, "StandaloneWindows")
                self.assertEqual(parsed.fields[:2], (GUID, PS4ID))


if __name__ == "__main__":
    unittest.main()
