"""Native-bound player command manifest; static only, no target execution."""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path
import bisect
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path
import capstone
import pefile

ROOT = workspace()
OUT = ROOT / 'results'
NATIVE = ROOT / 'work/evidence/ghidra/functions'
BIN = ROOT / 'work/evidence/GameAssembly.dll'
meta = json.loads((ROOT / 'work/decompiled/script.json').read_text(encoding='utf-8-sig'))
literals = json.loads((ROOT / 'work/decompiled/stringliteral.json').read_text(encoding='utf-8-sig'))
names = defaultdict(list)
for m in meta['ScriptMethod']: names[m['Address']].append(m['Name'])
starts = sorted(names)
literal_map = {int(x['address'], 16): x['value'] for x in literals}

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def evidence(rva):
    path = NATIVE / f'{rva:x}.c'
    if not path.exists(): raise RuntimeError(f'Missing native evidence: {rva:x}')
    return {'rva': hex(rva), 'path': str(path.relative_to(ROOT)).replace('\\','/'), 'sha256': digest(path)}
def stable_hash(value):
    h = 23
    units = value.encode('utf-16-le')
    for (c,) in struct.iter_unpack('<H', units): h = (h * 31 + c) & 0xffffffff
    return h if h < 0x80000000 else h - 0x100000000

rows = [
    ('speed', 1, 0x614560, 0x24f9ac8, 0, 'float32 little endian, exactly4 bytes', None),
    ('transform_sync', 0, 0x12687e0, 0x24faf80, 1, 'byte presence flag + optional Vector3; byte flag + optional Quaternion; byte flag + optional Vector3', 0x24fb1a0),
    ('teleport', 0, 0x1268cc0, 0x24fb008, 0, 'Vector3 destination, exactly12 bytes', 0x24fb228),
    ('teleport_rotation', 0, 0x1268b30, 0x24fb090, 0, 'Vector3 destination then Quaternion rotation, exactly28 bytes', 0x24fb2b0),
    ('obsolete_teleport_rotation', 0, 0x1268910, 0x24fb118, 0, 'Vector3 destination then Quaternion rotation, exactly28 bytes; shares modern two-argument user body', 0x24fb2b0),
]
commands = []
for name, component, rva, literal, channel, payload, reply in rows:
    value = literal_map[literal]
    commands.append({'name': name, 'component_index': component, 'rva':hex(rva), 'signature_literal_rva':hex(literal), 'signature':value,
        'function_hash_signed_int32':stable_hash(value), 'channel':channel, 'requires_authority':True, 'payload':payload,
        'reply_rpc':None if reply is None else {'signature':literal_map[reply], 'literal_rva':hex(reply), 'function_hash_signed_int32':stable_hash(literal_map[reply]), 'include_owner':True},
        'evidence':evidence(rva), 'runtime_reachability_proven':False})

# A conservative executable-section E8 scan. Boundary verification is a linear
# decode from the exact metadata method entry. Indirect/inlined calls omitted.
pe = pefile.PE(str(BIN), fast_load=True)
decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
targets = {r[2] for r in rows} | {0x614970}
references = []
decode_cache = {}
for section in pe.sections:
    if not section.Characteristics & 0x20000000: continue
    raw, base = section.get_data(), section.VirtualAddress
    offset = raw.find(b'\xe8')
    while offset >= 0:
        if offset + 5 <= len(raw):
            call_rva = base + offset
            target = call_rva + 5 + struct.unpack_from('<i', raw, offset + 1)[0]
            if target in targets:
                ix = bisect.bisect_right(starts, call_rva) - 1
                if ix >= 0:
                    caller = starts[ix]
                    end = starts[ix + 1] if ix + 1 < len(starts) else base + len(raw)
                    if caller <= call_rva < end and caller >= base and end - caller <= 65536:
                        if caller not in decode_cache:
                            code = raw[caller-base:end-base]
                            decode_cache[caller] = {i.address for i in decoder.disasm(code,caller) if i.mnemonic == 'call'}
                        if call_rva in decode_cache[caller]:
                            references.append({'call_rva':hex(call_rva), 'target_rva':hex(target), 'caller_rva':hex(caller), 'caller_names':names[caller],
                                'pseudocode_available':(NATIVE/f'{caller:x}.c').exists(), 'instruction_boundary_verified':True})
        offset = raw.find(b'\xe8', offset+1)

source_rvas = [0x127f270, 0x1284a00, 0x1284d50, 0x12db260, 0x12da160, 0x12d89a0,
    0x614850, 0x614240, 0x614970, 0x614380, 0x614040, 0x1270f70,
    0x1270400, 0x12708c0, 0x12707a0, 0x126cf50, 0x126cb90]
# Nullable writer RVAs are selected by metadata, avoiding guessed hex labels.
source_rvas = [x for x in source_rvas if (NATIVE/f'{x:x}.c').exists()]
source_rvas += [m['Address'] for m in meta['ScriptMethod'] if m['Name'] in (
    'Mirror.NetworkWriterExtensions$$WriteVector3Nullable', 'Mirror.NetworkWriterExtensions$$WriteQuaternionNullable')]
data = {'format_version':1, 'scope':'Static root-player Mirror command contracts; not all scene entities or runtime proof',
    'binary_sha256':digest(BIN), 'game_launched':False, 'listener_started':False, 'networking_parity_proven':False,
    'hash_algorithm':'UInt32 unchecked, seed23, for each UTF16 code unit h=h*31+c; transmit full signed Int32 bits',
    'component_provenance':'mirror-player-state.json rootNetworkBehaviours: index0 disabled Mirror.NetworkTransform(clientAuthority1), index1 NebulaPlayerSyncVars',
    'commands':commands, 'direct_call_references':references, 'native_evidence':[evidence(x) for x in dict.fromkeys(source_rvas)],
    'source_files':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':digest(p)} for p in (
        ROOT/'work/decompiled/stringliteral.json',ROOT/'work/decompiled/script.json',
        OUT/'mirror-server/UnityProject/Assets/Preservation/NebulaMirrorCommands.cs',OUT/'protocol/mirror-player-state.json')],
    'replacement_policy_and_limits':[
        'SetSpeed sends a float but its shipped UserCode method is an empty return at sharedRVA0x35a740. InvokeUserCode reads the float and checks type/server state without assigning it. Therefore assigning the accepted value to cached speed and replicating SyncVar is an explicit new local server policy, inferred from the client speed SyncVar consumer, not recovered server behavior.',
        'Transform command payload/RPC mapping and includeOwner/channel flags are native-derived. The raw replacement caches authoritative pose and forwards the matching RPC rather than running an original server-side interpolation component.',
        'All commands require a bound ready spawned connection and its own netId. Malformed, extra, nonfinite and degenerate-rotation values are rejected as local validation.',
        'Prefab component0 is disabled; registration does not prove ordinary gameplay sends its commands. The direct E8 references list has a bounded linear-instruction scope and omits indirect/virtual/inlined calls.',
        'No additional NetworkIdentity scene-object registry, original scheduling/authority, server physics, anticheat or original speed thresholds are established by these contracts.',
    ]}
(OUT/'protocol/mirror-command-contracts.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
lines = ['# Root player Mirror command contracts','','Static native evidence plus compiled codec implementation. No game, listener or connection was executed.','','| Component | Command | Hash (signed Int32) | Channel | Payload |','|---:|---|---:|---:|---|']
for c in commands: lines.append(f'| {c["component_index"]} | {c["name"]} | {c["function_hash_signed_int32"]} | {c["channel"]} | {c["payload"]} |')
lines += ['','Channel0 is reliable, channel1 is the historical unreliable path (Telepathy itself uses TCP). Every registered command requires ownership. Function hashes use all32 bits; a modern ushort-hash implementation would mismatch this client.','',
    'The native transform command handlers forward the corresponding RPC to observers including the owner; the owner client has its own authority suppression in the transform component. The obsolete teleport-and-rotate command invokes the current two-argument RPC. Initial transform state is only emitted for initial spawn; ordinary transform updates travel through RPC/custom opcode2.','',
    '## Observations and replacement policy','']
lines += ['- '+x for x in data['replacement_policy_and_limits']]
lines += ['','The JSON includes exact signatures, string-literal RVAs, method bodies, hashes, verified bounded E8 references and all evidence-file digests. Native pseudocode is not the original C# or the retired server.','']
(OUT/'protocol/mirror-command-contracts.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'commands':[{k:c[k] for k in ('name','function_hash_signed_int32')} for c in commands], 'direct_references':len(references)},indent=2))
