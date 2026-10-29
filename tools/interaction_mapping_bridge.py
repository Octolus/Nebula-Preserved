"""Offline prototype for translating Nebula's session-local interaction IDs.

The shipped client sends only integer IDs in TCP 8/9/10/94.  This prototype is
not a wire extension and does not alter the game.  It specifies the smallest
compatibility bridge needed by a patched client and server: each client first
binds its local IDs to trusted semantic keys, then the server relays using the
recipient's local IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


GENERIC = "generic"
OCCUPABLE = "occupable"
KINDS = frozenset((GENERIC, OCCUPABLE))


class MappingRejected(ValueError):
    """The announced registry cannot safely be used for translation."""


@dataclass(frozen=True)
class ContractEntry:
    key: str
    kind: str
    allowed: bool = True
    extension_count: int = 0

    def __post_init__(self) -> None:
        if not self.key or self.kind not in KINDS or self.extension_count < 0:
            raise ValueError("invalid contract entry")
        if self.kind == OCCUPABLE and self.extension_count:
            raise ValueError("occupables do not carry generic extensions")


@dataclass(frozen=True)
class RegistryContract:
    namespace: str
    epoch: str
    entries: tuple[ContractEntry, ...]

    def __post_init__(self) -> None:
        if not self.namespace or not self.epoch or not self.entries:
            raise ValueError("registry namespace, epoch and entries are required")
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate semantic key in contract")

    @property
    def by_key(self) -> dict[str, ContractEntry]:
        return {entry.key: entry for entry in self.entries}


@dataclass(frozen=True)
class LocalBinding:
    key: str
    kind: str
    local_id: int


@dataclass
class _PeerRegistry:
    epoch: str
    sequence: int
    bindings: tuple[LocalBinding, ...]


class InteractionMappingBridge:
    """Strict, all-or-nothing semantic mapping and per-recipient translation."""

    def __init__(self, contracts: Iterable[RegistryContract]):
        self.contracts = {contract.namespace: contract for contract in contracts}
        if not self.contracts:
            raise ValueError("at least one trusted contract is required")
        self._peers: dict[str, dict[str, _PeerRegistry]] = {}
        self._generic_state: dict[str, tuple[bool, tuple[str, ...]]] = {}
        self._occupants: dict[str, str] = {}

    def announce(
        self,
        peer: str,
        namespace: str,
        epoch: str,
        sequence: int,
        bindings: Iterable[LocalBinding],
    ) -> None:
        """Validate and atomically replace one peer's complete namespace map."""
        if not peer or namespace not in self.contracts or sequence < 0:
            raise MappingRejected("unknown peer/namespace or invalid sequence")
        contract = self.contracts[namespace]
        if epoch != contract.epoch:
            raise MappingRejected("registry epoch does not match trusted contract")
        proposed = tuple(bindings)
        expected = contract.by_key
        if {binding.key for binding in proposed} != set(expected):
            raise MappingRejected("announcement must contain the exact trusted key set")
        if len(proposed) != len(expected):
            raise MappingRejected("duplicate semantic key")
        for binding in proposed:
            entry = expected[binding.key]
            if binding.kind != entry.kind or binding.local_id < 0:
                raise MappingRejected("binding kind or local ID is invalid")
        current = self._peers.get(peer, {}).get(namespace)
        if current is not None and sequence <= current.sequence:
            raise MappingRejected("announcement sequence is stale")

        # IDs are global per native registry kind, not per namespace.  Validate
        # against the peer's other namespace maps before committing replacement.
        candidate = {
            other_namespace: registry
            for other_namespace, registry in self._peers.get(peer, {}).items()
            if other_namespace != namespace
        }
        candidate[namespace] = _PeerRegistry(epoch, sequence, proposed)
        seen: set[tuple[str, int]] = set()
        for registry in candidate.values():
            for binding in registry.bindings:
                identity = (binding.kind, binding.local_id)
                if identity in seen:
                    raise MappingRejected("local ID collides across registry namespaces")
                seen.add(identity)
        self._peers.setdefault(peer, {})[namespace] = candidate[namespace]

    def revoke(self, peer: str, namespace: str) -> None:
        self._peers.get(peer, {}).pop(namespace, None)

    def invalidate_epoch(self, namespace: str) -> None:
        """Freeze a changed namespace and discard state that cannot migrate safely."""
        if namespace not in self.contracts:
            raise MappingRejected("unknown namespace")
        keys = set(self.contracts[namespace].by_key)
        for registries in self._peers.values():
            registries.pop(namespace, None)
        for key in keys:
            self._generic_state.pop(key, None)
            self._occupants.pop(key, None)

    def _resolve_sender(self, peer: str, kind: str, local_id: int) -> ContractEntry:
        matches: list[ContractEntry] = []
        for namespace, registry in self._peers.get(peer, {}).items():
            for binding in registry.bindings:
                if binding.kind == kind and binding.local_id == local_id:
                    matches.append(self.contracts[namespace].by_key[binding.key])
        if len(matches) != 1:
            raise MappingRejected("local ID is unbound or ambiguous")
        entry = matches[0]
        if not entry.allowed:
            raise MappingRejected("semantic key is deferred by preservation policy")
        return entry

    def _recipient_id(self, peer: str, entry: ContractEntry) -> int:
        for registry in self._peers.get(peer, {}).values():
            for binding in registry.bindings:
                if binding.key == entry.key and binding.kind == entry.kind:
                    return binding.local_id
        raise MappingRejected("recipient has no binding for semantic key")

    def relay_generic(
        self,
        sender_peer: str,
        actor_guid: str,
        local_id: int,
        state: bool,
        extensions: Iterable[str],
        recipients: Iterable[str],
    ) -> dict[str, tuple[str, int, bool, tuple[str, ...]]]:
        """Translate opcode 94.  The caller must include the sender in recipients."""
        entry = self._resolve_sender(sender_peer, GENERIC, local_id)
        extension_tuple = tuple(extensions)
        if len(extension_tuple) != entry.extension_count:
            raise MappingRejected("extension count does not match trusted contract")
        output = {
            peer: (actor_guid, self._recipient_id(peer, entry), bool(state), extension_tuple)
            for peer in recipients
        }
        if sender_peer not in output:
            raise MappingRejected("opcode 94 acceptance must be echoed to its sender")
        self._generic_state[entry.key] = (bool(state), extension_tuple)
        return output

    def generic_snapshot(self, peer: str) -> list[tuple[int, bool, tuple[str, ...]]]:
        result: list[tuple[int, bool, tuple[str, ...]]] = []
        for key, (state, extensions) in self._generic_state.items():
            entry = self._entry(key)
            try:
                local_id = self._recipient_id(peer, entry)
            except MappingRejected:
                continue
            result.append((local_id, state, extensions))
        return sorted(result)

    def occupancy_query(
        self, peer: str, requester_guid: str, local_id: int
    ) -> tuple[int, tuple[str, int] | tuple[str, int, str]]:
        """Translate opcode 8 to the exact free (S2C10) or held (S2C9) envelope."""
        entry = self._resolve_sender(peer, OCCUPABLE, local_id)
        occupant = self._occupants.get(entry.key)
        if occupant is None:
            # 0x5dc440 ignores token 0 but requires token 1 to be the integer ID.
            return (10, ("", local_id))
        return (9, (requester_guid, local_id, occupant))

    def occupancy_claim(
        self,
        sender_peer: str,
        requester_guid: str,
        local_id: int,
        recipients: Iterable[str],
    ) -> dict[str, tuple[str, int, str]]:
        """Translate opcode 9 and broadcast recipient-specific IDs."""
        entry = self._resolve_sender(sender_peer, OCCUPABLE, local_id)
        occupant = self._occupants.get(entry.key)
        if occupant is not None and occupant != requester_guid:
            raise MappingRejected("occupable is already held")
        output = {
            peer: (requester_guid, self._recipient_id(peer, entry), requester_guid)
            for peer in recipients
        }
        if sender_peer not in output:
            raise MappingRejected("occupancy acceptance must include its sender")
        self._occupants[entry.key] = requester_guid
        return output

    def occupancy_leave(
        self,
        sender_peer: str,
        requester_guid: str,
        local_id: int,
        recipients: Iterable[str],
    ) -> dict[str, tuple[str, int]]:
        """Translate opcode 10 and reject a non-occupant's release."""
        entry = self._resolve_sender(sender_peer, OCCUPABLE, local_id)
        if self._occupants.get(entry.key) != requester_guid:
            raise MappingRejected("only the current occupant may release")
        output = {peer: (requester_guid, self._recipient_id(peer, entry)) for peer in recipients}
        if sender_peer not in output:
            raise MappingRejected("occupancy release must include its sender")
        del self._occupants[entry.key]
        return output

    def _entry(self, key: str) -> ContractEntry:
        matches = [contract.by_key[key] for contract in self.contracts.values() if key in contract.by_key]
        if len(matches) != 1:
            raise MappingRejected("semantic key is missing or ambiguous across contracts")
        return matches[0]


def static_key(
    scene: str, sibling_index_chain: str, concrete_class: str, component_slot: int
) -> str:
    """Runtime-derivable key under an exact, pre-audited binary/bundle profile."""
    if not scene or not sibling_index_chain or not concrete_class or component_slot < 0:
        raise ValueError("invalid static key fields")
    return f"static:{scene.lower()}:{sibling_index_chain}:{concrete_class}:{component_slot}"


def furniture_key(
    layout_digest: str,
    ground_index: int,
    item_id: str,
    descendant_path: str,
    component_slot: int,
    kind: str,
) -> str:
    """Stable only inside one durable saved-layout epoch."""
    if not layout_digest or ground_index < 0 or component_slot < 0 or kind not in KINDS:
        raise ValueError("invalid furniture key fields")
    return (
        f"furniture:{layout_digest}:{ground_index}:{item_id}:"
        f"{descendant_path}:{component_slot}:{kind}"
    )
