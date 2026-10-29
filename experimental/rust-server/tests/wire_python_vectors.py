"""Regenerate fixture data by executing the preserved Python wire module."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
source_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
source = source_root / 'backend/wire.py'
spec = importlib.util.spec_from_file_location('preserved_wire', source)
wire = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wire
spec.loader.exec_module(wire)

fixture_dir = Path(__file__).resolve().parent
csharp = json.loads((fixture_dir / 'wire_csharp_vectors.json').read_text(encoding='utf-8-sig'))
for item in csharp['crypto']:
    assert wire.encrypt(item['plaintext']) == item['ciphertext']
    assert wire.decrypt(item['ciphertext']) == item['plaintext']

crypto = []
for count in (0, 1, 15, 16, 17, 31, 32, 33, 255, 4096):
    for unit in ('a', '\u00e9', '\U0001f680', '#'):
        plaintext = unit * count
        crypto.append({'plaintext': plaintext, 'ciphertext': wire.encrypt(plaintext)})

json_values = [None, False, True, 0, -1, 18446744073709551615, '', '#', '##', '\\u0023',
               'quote"\\', '\0\b\t\n\f\r', '\u007f', '\u0080', '\U0001f680', '\u2028',
               {'nested': ['#', None, True, 0], 'text': 'é🚀#'}, {'z': 1, 'a': 2},
               0.0, -0.0, 1.0, 1e-4, 1e-5, 1e-7, 1e15, 1e16, 1e20, 1e23,
               1.2345678901234567, -12345.678, 5e-324, 1.7976931348623157e308]
requests = []
for plaintext in ('#PS4', '##PS4', 'a#b#c#PS4', 'PS4##StandaloneWindows#PS4',
                  'guid#account#text#with#hashes#StandaloneWindows'):
    for maxsplit in (None, 0, 1, 2, 99):
        request = wire.Request.parse(plaintext, maxsplit=-1 if maxsplit is None else maxsplit)
        requests.append({'plaintext': plaintext, 'maxsplit': maxsplit,
                         'fields': request.fields, 'platform': request.platform})

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
invalid_ciphertexts = ['', '!', 'a', '====', 'AAAA', 'AA AA', 'AAAA\n',
    base64.b64encode(AES.new(wire.KEY, AES.MODE_ECB).encrypt(b'\0' * 16)).decode(),
    base64.b64encode(AES.new(wire.KEY, AES.MODE_ECB).encrypt(pad(b'\xff', 16))).decode()]
for ciphertext in invalid_ciphertexts:
    try:
        wire.decrypt(ciphertext)
    except Exception:
        pass
    else:
        raise AssertionError(ciphertext)

sessions = [{'id': a, 'request_hash': b, 'guid': wire.session_guid(a, b)} for a,b in
            [('123456789', 'abcdef'), ('', ''), ('a#b', 'c#d'), ('é', '🚀')]]
noncanonical = 'QrnGrub9EXAqpBYR/qr3Gx=='
assert wire.decrypt(noncanonical) == ''
result = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'crypto': crypto, 'invalid_ciphertexts': invalid_ciphertexts,
          'noncanonical_base64': noncanonical,
          'json': [{'value': value, 'field': wire.json_field(value)} for value in json_values],
          'requests': requests, 'sessions': sessions,
          'invalid_requests': ['', 'a', 'a#', 'a#Windows', 'a#PS4\n', 'a#ps4',
                               'a#StandaloneWindows#junk']}
(fixture_dir / 'wire_python_vectors.json').write_text(json.dumps(result, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
print(f'Generated {len(crypto)} Python crypto, {len(json_values)} JSON, {len(requests)} request, {len(sessions)} GUID vectors; C# crypto cross-check passed.')
