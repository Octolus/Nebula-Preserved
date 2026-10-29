"""Closed local test-identity policy; no caller-supplied identity overrides."""
from ipaddress import IPv4Address, IPv4Network

from wire import ProtocolError


FIXED_TEST_IDENTITIES = {
    "local-preservation-test-1": "[TEST] Preservation Client 1",
    "local-preservation-test-2": "[TEST] Preservation Client 2",
}
RESERVED_ID_PREFIX = "local-preservation-test-"
RESERVED_NAME_PREFIX = "[TEST] Preservation Client "
PRIVATE_V4 = tuple(IPv4Network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))


def private_concrete_ipv4(value):
    """Only concrete loopback/RFC1918 endpoints can enable fixed test IDs."""
    try:
        address = IPv4Address(value)
    except ValueError:
        return False
    return not address.is_unspecified and any(address in network for network in PRIVATE_V4)


def reserved_id(value):
    return isinstance(value, str) and value.lower().startswith(RESERVED_ID_PREFIX.lower())


def reserved_name(value):
    return isinstance(value, str) and value.lower().startswith(RESERVED_NAME_PREFIX.lower())


def validate_identity(ps4_id, username, enabled):
    """Return the canonical username or reject every reserved-prefix variant."""
    expected = FIXED_TEST_IDENTITIES.get(ps4_id)
    has_reserved_id = reserved_id(ps4_id)
    has_reserved_name = reserved_name(username)
    if not has_reserved_id and not has_reserved_name:
        return username
    if not enabled:
        raise ProtocolError("Local test identities are disabled", 403)
    if expected is None or (username is not None and username != expected):
        raise ProtocolError("Invalid fixed local test identity", 403)
    return expected


def validate_lookup_username(username, enabled):
    if not reserved_name(username):
        return
    if not enabled or username not in FIXED_TEST_IDENTITIES.values():
        raise ProtocolError("Invalid fixed local test identity lookup", 403)

