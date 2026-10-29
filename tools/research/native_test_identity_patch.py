"""Prepare an isolated optional fixed-slot identity test candidate; never install it.

The original Steam initializer always runs. Only backend-facing PS4Info fields
may be replaced by the sibling helper, and only for its two fixed test slots.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile

from interaction_registry_patch import coff

ROOT = workspace()
LAYER = ROOT/'results/client-fixes/native_test_identity'
SOURCE_SHA256 = 'c11dc93f3f67bb09781d9c097ce85cc2e497af9bf83efabaf279ec2b03b0f3d5'
ASM_SHA256 = '6de2317361dbc760638f92ddf3deb7a8197ca0fd1bfae71e0911a49f0d3e84ae'
CPP_SHA256 = '528726057a00093585d9e998cdf36a2b1a7ac3f3d1c1e29aadc25f30e6c4686f'
OBJECT_SHA256 = 'bb556e519a6259d47a37405c7812c0808e07e7ef784a1cb35a556c7e2705cc10'
DLL_SHA256 = 'a3d394fe56de326ec097a2077132505a9311c2cb7e676a3f2532dbec21f51c73'
CALL_RVA = 0x42ac8d
ORIGINAL_RVA = 0x4ca510
TARGETS = {
    'OriginalSteamManagerInit': ORIGINAL_RVA,
    'IatLoadLibraryExW': 0x1dd2440,
    'IatGetProcAddress': 0x1dd20c0,
    'IatGetModuleHandleW': 0x1dd20b8,
    'IatGetModuleFileNameW': 0x1dd2318,
}
SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1)//alignment*alignment


def build(source: bytes, obj: bytes, dll: bytes):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError('Source must be the exact reviewed c11 settings/neck/save-snapshot stage')
    if (SHA(obj) != OBJECT_SHA256 or SHA(dll) != DLL_SHA256 or
            SHA((LAYER/'native_test_identity.s').read_bytes()) != ASM_SHA256 or
            SHA((LAYER/'native_test_identity.cpp').read_bytes()) != CPP_SHA256):
        raise ValueError('Helper source/object/DLL pins differ')
    helper = pefile.PE(data=dll, fast_load=False)
    imports = {entry.dll.decode().lower() for entry in helper.DIRECTORY_ENTRY_IMPORT}
    exports = {entry.name.decode() for entry in helper.DIRECTORY_ENTRY_EXPORT.symbols if entry.name}
    if (helper.FILE_HEADER.Machine != 0x8664 or helper.OPTIONAL_HEADER.Magic != 0x20b or
            exports != {'NebulaTestIdentity_Apply', 'NebulaTestIdentity_AppliedSlot'} or
            any(name != 'kernel32.dll' and not name.startswith('api-ms-win-crt-') for name in imports)):
        raise ValueError('Unexpected helper architecture, exports or runtime dependency')
    pe = pefile.PE(data=source, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b:
        raise ValueError('Expected AMD64 PE32+')
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError('Signed or overlay input is unsupported')
    original_call = b'\xe8'+struct.pack('<i', ORIGINAL_RVA-(CALL_RVA+5))
    if pe.get_data(CALL_RVA, 5) != original_call:
        raise ValueError('Original SteamManager.Init call differs')
    # Includes the caller's5th-argument write and exact three instance fields.
    context = bytes.fromhex('4c8d83e000000048c744242000000000488d53284c8bcf488bcee87ef80900')
    if pe.get_data(CALL_RVA-26, len(context)) != context:
        raise ValueError('Original five-argument account/name context differs')
    last = pe.sections[-1]
    if (last.Name.rstrip(b'\0') != b'.nbi' or last.Characteristics != 0x60000020 or
            last.PointerToRawData+last.SizeOfRawData != len(source) or
            last.VirtualAddress != max(section.VirtualAddress for section in pe.sections) or
            last.Misc_VirtualSize > last.SizeOfRawData or
            any(section is not last and (section.PointerToRawData+section.SizeOfRawData > last.PointerToRawData or
                section.VirtualAddress+max(section.Misc_VirtualSize, section.SizeOfRawData) > last.VirtualAddress)
                for section in pe.sections)):
        raise ValueError('Expected final nonoverlapping RX .nbi at file/RVA end')
    sections, symbols = coff(obj)
    by_name = {row['name']: row for row in sections}
    if set(by_name) != {'.text', '.data', '.bss', '.xdata', '.pdata'}:
        raise ValueError('Unexpected wrapper COFF section set')
    if by_name['.data']['data'] or by_name['.bss']['data'] or by_name['.xdata']['relocs']:
        raise ValueError('Wrapper contains unsupported writable data/unwind relocations')
    new_rva = last.VirtualAddress+last.SizeOfRawData
    code, xdata = by_name['.text']['data'], by_name['.xdata']['data']
    public = {row['name']: row['value'] for row in symbols.values()
              if row['name'] in ('TestIdentityInit', 'TestIdentityResolve') and row['section'] == 1}
    if set(public) != {'TestIdentityInit', 'TestIdentityResolve'}:
        raise ValueError('Wrapper symbols missing or outside text')
    relocations = []
    for offset, symbol, kind in by_name['.text']['relocs']:
        if kind != 4 or symbol['name'] not in TARGETS:
            raise ValueError('Unexpected wrapper text relocation')
        target = TARGETS[symbol['name']]
        addend = struct.unpack_from('<i', code, offset)[0]
        struct.pack_into('<i', code, offset, target+addend-(new_rva+offset+4))
        relocations.append({'operand_rva': hex(new_rva+offset), 'symbol': symbol['name'], 'target_rva': hex(target)})
    xdata_at = ALIGN(len(code), 4)
    xdata_rva = new_rva+xdata_at
    section_names = {i+1: row['name'] for i, row in enumerate(sections)}
    pdata = by_name['.pdata']['data']
    for offset, symbol, kind in by_name['.pdata']['relocs']:
        base = new_rva if section_names.get(symbol['section']) == '.text' else xdata_rva if section_names.get(symbol['section']) == '.xdata' else None
        if kind != 3 or base is None:
            raise ValueError('Unexpected wrapper runtime-function relocation')
        addend = struct.unpack_from('<I', pdata, offset)[0]
        struct.pack_into('<I', pdata, offset, base+symbol['value']+addend)
    generated = [struct.unpack_from('<III', pdata, at) for at in range(0, len(pdata), 12)]
    if len(pdata) != 24 or len(generated) != 2 or generated != sorted(generated):
        raise ValueError('Expected exactly two sorted wrapper runtime functions')
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    wrappers = []
    for begin, end, unwind in generated:
        decoded = list(md.disasm(bytes(code[begin-new_rva:end-new_rva]), begin))
        if not decoded or sum(row.size for row in decoded) != end-begin or decoded[-1].mnemonic != 'ret':
            raise ValueError('Wrapper does not completely decode through return')
        offset = unwind-xdata_rva
        if offset < 0 or offset+4 > len(xdata) or xdata[offset] != 1:
            raise ValueError('Unsupported wrapper unwind header')
        wrappers.append({'begin': hex(begin), 'end': hex(end), 'unwind': hex(unwind),
                         'instructions': [{'rva': hex(row.address), 'bytes': row.bytes.hex(), 'instruction': row.mnemonic+' '+row.op_str} for row in decoded]})
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    original_table = pe.get_data(directory.VirtualAddress, directory.Size)
    if not original_table or len(original_table) != directory.Size or len(original_table) % 12:
        raise ValueError('Malformed original exception table')
    rows = [struct.unpack_from('<III', original_table, at) for at in range(0, len(original_table), 12)]
    expanded = rows+generated
    if (expanded != sorted(expanded) or any(a >= b for a, b, _ in expanded) or
            any(expanded[i][1] > expanded[i+1][0] for i in range(len(expanded)-1))):
        raise ValueError('Runtime functions are unsorted or overlap')
    table_at = ALIGN(xdata_at+len(xdata), 4)
    blob = bytes(code).ljust(xdata_at, b'\0')+bytes(xdata)
    blob = blob.ljust(table_at, b'\0')+b''.join(struct.pack('<III', *row) for row in expanded)
    virtual_size = last.SizeOfRawData+len(blob)
    raw_size = ALIGN(virtual_size, pe.OPTIONAL_HEADER.FileAlignment)
    result = bytearray(source)
    call_at = pe.get_offset_from_rva(CALL_RVA)
    replacement = b'\xe8'+struct.pack('<i', new_rva+public['TestIdentityInit']-(CALL_RVA+5))
    result[call_at:call_at+5] = replacement
    fields = [
        (last.get_field_absolute_offset('Misc_VirtualSize'), virtual_size, 'last_section.VirtualSize'),
        (last.get_field_absolute_offset('SizeOfRawData'), raw_size, 'last_section.SizeOfRawData'),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfCode'), pe.OPTIONAL_HEADER.SizeOfCode+raw_size-last.SizeOfRawData, 'SizeOfCode'),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), ALIGN(last.VirtualAddress+virtual_size, pe.OPTIONAL_HEADER.SectionAlignment), 'SizeOfImage'),
        (directory.get_file_offset(), new_rva+table_at, 'ExceptionDirectory.RVA'),
        (directory.get_file_offset()+4, len(expanded)*12, 'ExceptionDirectory.Size'),
        (pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0, 'CheckSum'),
    ]
    for offset, value, _ in fields:
        struct.pack_into('<I', result, offset, value)
    result.extend(blob.ljust(raw_size-last.SizeOfRawData, b'\0'))
    parsed = pefile.PE(data=bytes(result), fast_load=True)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), parsed.generate_checksum())
    restored = bytearray(result[:len(source)])
    for offset, length in [(call_at, 5)]+[(offset, 4) for offset, _, _ in fields]:
        restored[offset:offset+length] = source[offset:offset+length]
    if restored != source:
        raise ValueError('Unexpected mutation outside the one call and PE bookkeeping')
    parsed = pefile.PE(data=bytes(result), fast_load=True)
    if (parsed.FILE_HEADER.NumberOfSections != pe.FILE_HEADER.NumberOfSections or any(
            (a.Name, a.VirtualAddress, a.PointerToRawData, a.Characteristics) !=
            (b.Name, b.VirtualAddress, b.PointerToRawData, b.Characteristics)
            for a, b in zip(pe.sections, parsed.sections)) or
            parsed.get_data(new_rva, len(code)) != code or
            parsed.get_data(new_rva+table_at, len(expanded)*12) != b''.join(struct.pack('<III', *row) for row in expanded)):
        raise ValueError('Reparsed section/wrapper/runtime-function verification failed')
    return bytes(result), {
        'format_version': 1, 'kind': 'isolated_fixed_slot_native_identity_candidate',
        'source_sha256': SHA(source), 'candidate_sha256': SHA(result),
        'helper_sha256': SHA(dll), 'object_sha256': SHA(obj), 'asm_sha256': ASM_SHA256, 'cpp_sha256': CPP_SHA256,
        'target_executed': False, 'installation_changed': False,
        'patch': {'call_rva': hex(CALL_RVA), 'file_offset': hex(call_at), 'original': original_call.hex(),
                  'replacement': replacement.hex(), 'wrapper_rva': hex(new_rva+public['TestIdentityInit']),
                  'original_target_rva': hex(ORIGINAL_RVA)},
        'wrappers': wrappers, 'relocations': relocations,
        'runtime_functions': {'original_preserved': len(rows), 'added': 2,
                              'table_rva': hex(new_rva+table_at), 'table_size': len(expanded)*12},
        'allowed_headers': [{'name': name, 'file_offset': hex(offset), 'size': 4} for offset, _, name in fields],
        'helper_exports': sorted(exports), 'helper_import_dlls': sorted(imports),
        'environment': {'name': 'NEBULA_PRESERVATION_TEST_SLOT',
                        'values': {'1': {'account': 'local-preservation-test-1', 'name': '[TEST] Preservation Client 1'},
                                   '2': {'account': 'local-preservation-test-2', 'name': '[TEST] Preservation Client 2'}},
                        'missing_or_invalid': 'Leave original fields unchanged'},
        'modified_fields': ['PS4Info+0x28 sAccountId', 'PS4Info+0xd8 PS4ID', 'PS4Info+0xe0 userName'],
        'preserved': ['Original SteamManager.Init always called with all five argument slots',
                      'All Steam API ownership/context/callback and real identity paths',
                      'SteamManager+0x18/+0x20 and commerce identity', 'PS4Info SessionGUID generation',
                      'Every original byte except one rel32 call and explicit PE bookkeeping',
                      'Original runtime-function table rows and section identity/permissions'],
        'limitations': ['Test-only; backend must explicitly allow these two fixed IDs on local/private endpoints.',
                        'No simultaneous SteamAPI_Init or two-native-client behavior has been observed.',
                        'Both processes share PlayerPrefs/cache; avoid concurrent settings writes.',
                        'STMGetUserInfo queues its real-Steam country/currency request before the override.',
                        'Heap readability checks are guards, not a concurrent memory safety proof.',
                        'Three GC barrier stores are ordered and main-thread only, not transactional.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--object', required=True, type=Path)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    inputs = {path.resolve(strict=True) for path in (args.source, args.object, args.helper)}
    outputs = [args.spec.resolve()]+([args.destination.resolve(), args.destination.resolve().parent/'NebulaTestIdentity.dll'] if args.destination else [])
    if (len(outputs) != len(set(outputs)) or any(path.exists() or path in inputs or
            any(part.lower() == 'steamapps' for part in path.parts) for path in outputs)):
        parser.error('Outputs must be new distinct paths outside steamapps')
    try:
        source_bytes, object_bytes, helper_bytes = args.source.read_bytes(), args.object.read_bytes(), args.helper.read_bytes()
        candidate, report = build(source_bytes, object_bytes, helper_bytes)
    except (ValueError, KeyError, struct.error) as exc:
        parser.error(str(exc))
    report['patcher_sha256'] = SHA(Path(__file__).read_bytes())
    report['candidate_written'] = args.destination is not None
    for path in outputs: path.parent.mkdir(parents=True, exist_ok=True)
    if args.destination:
        with args.destination.open('xb') as stream: stream.write(candidate)
        with (args.destination.parent/'NebulaTestIdentity.dll').open('xb') as stream: stream.write(helper_bytes)
    with args.spec.open('x', encoding='utf-8') as stream: stream.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'specification': str(args.spec), 'candidate_sha256': report['candidate_sha256'], 'target_executed': False}))


if __name__ == '__main__': main()
