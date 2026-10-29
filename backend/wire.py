"""Recovered client framing; no transport or game process is started here."""
import base64
import hashlib
import json
from dataclasses import dataclass

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

KEY = hashlib.sha1(b"a56Bhg2Fbg789Lmk").digest()[:16]
PLATFORMS = {"PS4": 0, "StandaloneWindows": 1}


def encrypt(plaintext: str) -> str:
    # Server replies do NOT append the client-side platform trailer.
    return base64.b64encode(AES.new(KEY, AES.MODE_ECB).encrypt(
        pad(plaintext.encode("utf-8"), 16))).decode("ascii")


def decrypt(ciphertext: str) -> str:
    return unpad(AES.new(KEY, AES.MODE_ECB).decrypt(
        base64.b64decode(ciphertext, validate=True)), 16).decode("utf-8")


def session_guid(ps4_id: str, request_hash: str) -> str:
    # PS4Info.GetHashSha256: Encoding.ASCII and byte.ToString("x2").
    source = (ps4_id + "#" + request_hash).encode("ascii", errors="replace")
    return hashlib.sha256(source).hexdigest()[:32]


def json_field(value) -> str:
    # Split('#', None) happens before JSON decoding. JSON's Unicode escape
    # preserves a literal '#' without creating a spurious outer field.
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).replace("#", "\\u0023")


class ProtocolError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Request:
    fields: tuple[str, ...]
    platform: str

    @classmethod
    def parse(cls, plaintext: str, maxsplit=-1):
        body, separator, platform = plaintext.rpartition("#")
        if not separator or platform not in PLATFORMS:
            raise ProtocolError("Missing or unsupported client platform trailer")
        return cls(tuple(body.split("#", maxsplit)), platform)

    def require(self, count: int):
        if len(self.fields) != count:
            raise ProtocolError(f"Expected {count} request fields, got {len(self.fields)}")
        return self.fields
