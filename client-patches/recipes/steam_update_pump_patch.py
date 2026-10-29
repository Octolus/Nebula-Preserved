"""Prepare an isolated opt-in background command candidate; never install it.

The original Steam update always runs first. Only fixed query/background actions
are enabled; no arbitrary target calls or writes are exposed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from interaction_registry_patch import coff

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / 'shims'
SOURCE_SHA256 = 'cd82cde50b71ea203fc09dc87153579f6cb504f1e9dfb74417408d602c704a74'
ASM_SHA256 = '8f64ec52d25e5dfc2299dc1423c70249827e48f1e79bedcbb3cb74b44f74bc34'
CPP_SHA256 = '330dbeba8062c58fe1d1f3e279753478bac6d89097f55d3b045af399ca31f204'
FILES_SHA256 = '849bd35f7c4a9b086e00af12be54eecdce4677e0c86ea4842ef8840e036764d7'
HEADER_SHA256 = 'f747361aeb5901807b52064279106eeda0f202f7c9c6b9bcbe7e593e56bbd10b'
OBJECT_SHA256 = 'df0555c5b0006ffd319c3e8fc6ee386e323c090c449eda074c8a53bea4ff08f5'
DLL_SHA256 = 'bee7c12e22f57b564aa5c7a384596aac2ad204d7c4a243891197da7bd566ebf1'
CALL_RVA = 0x422e20
ORIGINAL_RVA = 0x4ca810
TARGETS = {
    'OriginalSteamUpdate': ORIGINAL_RVA,
    'IatGetEnvironmentVariableW': 0x1dd21c0,
    'IatLoadLibraryExW': 0x1dd2440,
    'IatGetProcAddress': 0x1dd20c0,
    'IatGetModuleHandleW': 0x1dd20b8,
    'IatGetModuleFileNameW': 0x1dd2318,
}
SHA = lambda data: hashlib.sha256(data).hexdigest()
ALIGN = lambda value, alignment: (value + alignment - 1)//alignment*alignment


def build(source: bytes, obj: bytes):
    if SHA(source) != SOURCE_SHA256:
        raise ValueError('Source must be the exact reviewed cd82 eye/neck/settings/registry stage')
    if SHA(obj) != OBJECT_SHA256 or SHA((LAYER/'automation.s').read_bytes()) != ASM_SHA256:
        raise ValueError('Reviewed pump wrapper source/object differs')
    pe = pefile.PE(data=source, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b:
        raise ValueError('Expected AMD64 PE32+')
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size or pe.get_overlay_data_start_offset() is not None:
        raise ValueError('Signed or overlay input is unsupported')
    original_call = bytes.fromhex('488b8938020000')
    context = bytes.fromhex('488b89380200004885c9740733d2e9dd790a00c3cccccccccccccccccccccccc')
    if pe.get_data(CALL_RVA,32) != context or pe.get_data(ORIGINAL_RVA,7) != bytes.fromhex('33c9e9b9b21801'):
        raise ValueError('Original leaf Update / Steam callback context differs')
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
              if row['name'] in ('AutomationUpdate', 'AutomationResolve') and row['section'] == 1}
    if set(public) != {'AutomationUpdate', 'AutomationResolve'}:
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
    replacement = b'\xe9'+struct.pack('<i', new_rva+public['AutomationUpdate']-(CALL_RVA+5))+b'\x90\x90'
    result[call_at:call_at+7] = replacement
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
    for offset, length in [(call_at, 7)]+[(offset, 4) for offset, _, _ in fields]:
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
    if any(begin <= CALL_RVA < end for begin,end,_ in rows):
        raise ValueError('Original Update unexpectedly has a runtime function')
    return bytes(result), {
        'format_version':1,'kind':'isolated_opt_in_background_command_candidate',
        'source_sha256':SHA(source),'candidate_sha256':SHA(result),
        'helper_validation':'performed separately by final helper builder','object_sha256':SHA(obj),'asm_sha256':ASM_SHA256,
        'cpp_sha256':CPP_SHA256,'protocol_header_sha256':HEADER_SHA256,'files_header_sha256':FILES_SHA256,
        'target_executed':False,'installation_changed':False,
        'patch':{'entry_rva':hex(CALL_RVA),'file_offset':hex(call_at),'original':original_call.hex(),
                 'replacement':replacement.hex(),'wrapper_rva':hex(new_rva+public['AutomationUpdate'])},
        'wrappers':wrappers,'relocations':relocations,
        'runtime_functions':{'original_preserved':len(rows),'added':2,'table_rva':hex(new_rva+table_at),'table_size':len(expanded)*12},
        'allowed_headers':[{'name':name,'file_offset':hex(offset),'size':4} for offset,_,name in fields],
        'final_helper_built_separately':True,
        'environment':{'mode':'NEBULA_AUTOMATION=1','nonce':'NEBULA_AUTOMATION_NONCE=64 lowercase hex',
                       'directory':'NEBULA_AUTOMATION_DIR=absolute direct work/native-auto-session-*'},
        'actions':{'query':'synchronous bounded snapshot','background-on':'request Application.runInBackground true via runtime_invoke',
                   'editor.load_named':'rejected action_not_enabled_in_v1'},
        'limits':{'commands':256,'command_bytes':2048,'input_total_bytes':131072,'result_bytes':16384,
                  'output_total_bytes':8388608,'deadline_ms':120000,'session_ms':1800000,'poll_ms':50},
        'preserved':['Steam callback before every automation check','all original runtime rows and section identities/permissions',
                     'existing e493 registry DLL unchanged','cd82 eye guards, neck/settings/save bridge bytes'],
        'evidence_boundary':'offline candidate only; no game, target native method, listener, input, or foreground operation executed'
    }

