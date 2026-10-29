"""Offline exact-build 70 HTTPS endpoint/auth hooks plus queue-registration gate.

Preserve original inputs, UI, rendering, movement and economy callbacks. No
native library is loaded by this maintainer tool. New helper IATs stay inside
the reviewed read-only rdata padding and loader protection directory.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import capstone
import pefile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GET_PIN = "2e5fc6cdad195b25105be17bd3a89001a502b4b873b6c08c81a6c1fc891fed1a"
COFF_PIN = "6a65a9eab4340d759a5fc7509622b2fd741bae473fc8a954cadd7d7cb24ffdee"
UPDATE = 0x5e54c0
PROCESS = 0x5e5010
PREFIX = bytes.fromhex("33d2e949fbffff")
PROCESS_PREFIX = bytes.fromhex("41574883ec50803de3130502004c8bf9751f")
sha = lambda b: hashlib.sha256(b).hexdigest()
align = lambda n, a: (n + a - 1) // a * a

def require(ok, why):
    if not ok:
        raise ValueError(why)

def compose(source: bytes, obj: bytes, source_pin: str, object_pin: str):
    require(sha(source) == source_pin and sha(obj) == object_pin, "Exact reviewed network-stage/object required")
    reader = ROOT / "recipes/interaction_registry_patch.py"
    require(sha(reader.read_bytes()) == COFF_PIN, "COFF reader differs")
    spec = importlib.util.spec_from_file_location("network_only_coff", reader)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    inventory = (HERE / "unitywebrequest-get-calls.json").read_bytes()
    require(sha(inventory) == GET_PIN, "HTTPS inventory differs")
    calls = json.loads(inventory)
    require(calls["direct_call_count"] == 70 and len(calls["calls"]) == 70 and
            len({r["call_rva"] for r in calls["calls"]}) == 70 and calls["get_send_caller_sets_equal"] is True,
            "Exact 70 GET/Send callsite coverage required")
    pe = pefile.PE(data=source)
    require(pe.FILE_HEADER.Machine == 0x8664 and pe.OPTIONAL_HEADER.Magic == 0x20b, "AMD64 PE32+ required")
    require(not pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size and pe.get_overlay_data_start_offset() is None,
            "Signed/overlay input rejected")
    last = pe.sections[-1]
    require(last.Name.rstrip(b"\0") == b".nbi" and last.Characteristics == 0x60000020 and
            last.PointerToRawData + last.SizeOfRawData == len(source), "Terminal RX registry/settings stage required")
    require(pe.get_data(UPDATE, 7) == PREFIX and pe.get_data(PROCESS, len(PROCESS_PREFIX)) == PROCESS_PREFIX,
            "Original queue Update/drain differ")
    require(not any(r.struct.BeginAddress <= UPDATE < r.struct.EndAddress for r in pe.DIRECTORY_ENTRY_EXCEPTION),
            "Original Update must remain an unwind-free leaf")
    for row in calls["calls"]:
        rva = int(row["call_rva"], 16); off = pe.get_offset_from_rva(rva); raw = bytes.fromhex(row["original_hex"])
        require(off == int(row["file_offset"], 16) and len(raw) == 5 and raw[0] == 0xe8 and
                source[off:off+5] == raw and rva+5+struct.unpack_from("<i", raw, 1)[0] == 0x1d9b350,
                "Original HTTPS.Get callsite differs")
    sections, symbols = module.coff(obj)
    sec = {s["name"]: s for s in sections}; names = {i+1: s["name"] for i,s in enumerate(sections)}
    require(set(sec) == {".text", ".data", ".bss", ".xdata", ".pdata"} and
            not sec[".data"]["data"] and not sec[".bss"]["data"] and not sec[".xdata"]["relocs"],
            "Unexpected mutable state/COFF content")
    new = last.VirtualAddress + last.SizeOfRawData
    blob = bytearray(sec[".text"]["data"]); xat = align(len(blob), 4)
    blob.extend(bytes(xat-len(blob))); blob.extend(sec[".xdata"]["data"])
    public = {s["name"]: new+s["value"] for s in symbols.values()
              if names.get(s["section"]) == ".text" and s["storage"] == 2}
    require(set(public) == {"PublicGetThunk", "JoinQueueUpdate"}, "Only network wrappers may be exported")
    pdata = bytearray(sec[".pdata"]["data"])
    for offset, symbol, kind in sec[".pdata"]["relocs"]:
        require(kind == 3 and names.get(symbol["section"]) in (".text", ".xdata"), "Unexpected unwind relocation")
        base = new + (0 if names[symbol["section"]] == ".text" else xat)
        struct.pack_into("<I", pdata, offset, base + symbol["value"] + struct.unpack_from("<I", pdata, offset)[0])
    require(len(pdata) == 12, "Exactly one generated runtime function required")
    generated = tuple(struct.unpack("<III", pdata))
    require(generated[0] == public["JoinQueueUpdate"] and new <= generated[0] < generated[1] <= new+xat and
            new+xat <= generated[2] < new+len(blob), "Queue wrapper unwind bounds differ")
    unwind = bytes(blob[generated[2]-new:generated[2]-new+8])
    require(unwind == bytes.fromhex("0104010004620000"), "Exact 0x38 stack-allocation unwind required")
    old_imports = [source[r.struct.get_file_offset():r.struct.get_file_offset()+20] for r in pe.DIRECTORY_ENTRY_IMPORT]
    require(not {r.dll.lower() for r in pe.DIRECTORY_ENTRY_IMPORT} &
            {b"nebulaautomation.dll", b"nebulanetworkbridge.dll", b"nebulapublicaccess.dll"}, "Unexpected helper import")
    rdata = [s for s in pe.sections if s.Name.rstrip(b"\0") == b".rdata"]
    require(len(rdata) == 1, "Unique rdata required"); rdata = rdata[0]
    require((rdata.VirtualAddress, rdata.Misc_VirtualSize, rdata.SizeOfRawData, rdata.Characteristics) ==
            (0x1dd2000, 0x69a456, 0x69a600, 0x40000040), "Exact read-only rdata profile required")
    original_iat = pe.OPTIONAL_HEADER.DATA_DIRECTORY[12]
    require((original_iat.VirtualAddress, original_iat.Size) == (0x1dd2000, 0x790), "Original IAT differs")
    iat_offset = 0x69a458; padding_at = rdata.PointerToRawData+iat_offset
    require(not any(source[padding_at:padding_at+32]), "New helper IAT padding must be zero")
    targets = {"OriginalProcessTasks": PROCESS}; iat = bytearray(); added = []
    for dll, key, export in (("NebulaNetworkBridge.dll", "IatJoinReady", "NebulaAutomation_JoinQueueReady"),
                             ("NebulaPublicAccess.dll", "IatPublicGet", "NebulaPublicAccess_Get")):
        name_rva = new+len(blob); blob.extend(dll.encode()+b"\0")
        blob.extend(bytes(align(len(blob),2)-len(blob))); hint = new+len(blob); blob.extend(b"\0\0"+export.encode()+b"\0")
        blob.extend(bytes(align(len(blob),8)-len(blob))); int_rva = new+len(blob); thunk = struct.pack("<QQ", hint, 0); blob.extend(thunk)
        targets[key] = rdata.VirtualAddress+iat_offset+len(iat); iat.extend(thunk)
        added.append(struct.pack("<IIIII", int_rva, 0, 0, name_rva, targets[key]))
    require(len(iat) == 32, "Exactly two single-export helper IATs required")
    for offset, symbol, kind in sec[".text"]["relocs"]:
        require(kind == 4, "Only REL32 code operands supported")
        if symbol["section"] > 0:
            require(names.get(symbol["section"]) == ".text", "Internal relocation leaves wrapper text")
            target = new+symbol["value"]
        else:
            require(symbol["name"] in targets, "Unexpected wrapper external")
            target = targets[symbol["name"]]
        struct.pack_into("<i", blob, offset, target+struct.unpack_from("<i",blob,offset)[0]-(new+offset+4))
    import_at = align(len(blob),4); blob.extend(bytes(import_at-len(blob)))
    imports = b"".join(old_imports+added)+bytes(20); blob.extend(imports)
    oldrows = [(r.struct.BeginAddress,r.struct.EndAddress,r.struct.UnwindData) for r in pe.DIRECTORY_ENTRY_EXCEPTION]
    rows = sorted(oldrows+[generated])
    require(len(set(rows)) == len(rows) and all(rows[i][1] <= rows[i+1][0] for i in range(len(rows)-1)), "Unwind rows overlap")
    table_at = align(len(blob),4); blob.extend(bytes(table_at-len(blob))); blob.extend(b"".join(struct.pack("<III",*r) for r in rows))
    result = bytearray(source); allowed = set(); patches = []
    def write(fmt, at, *values):
        struct.pack_into(fmt,result,at,*values); allowed.update(range(at,at+struct.calcsize(fmt)))
    def patch(rva, size, target, opcode, name):
        off = pe.get_offset_from_rva(rva); before = source[off:off+size]
        after = bytes([opcode])+struct.pack("<i",target-rva-5)+b"\x90"*(size-5)
        result[off:off+size] = after; allowed.update(range(off,off+size))
        patches.append(dict(name=name,rva=hex(rva),before=before.hex(),after=after.hex(),target=hex(target)))
    for call in calls["calls"]:
        patch(int(call["call_rva"],16),5,public["PublicGetThunk"],0xe8,"HTTPS.Get")
    patch(UPDATE,7,public["JoinQueueUpdate"],0xe9,"Queue registration gate")
    raw_size = align(len(blob),pe.OPTIONAL_HEADER.FileAlignment)
    write("<I",last.get_field_absolute_offset("Misc_VirtualSize"),last.SizeOfRawData+len(blob))
    write("<I",last.get_field_absolute_offset("SizeOfRawData"),last.SizeOfRawData+raw_size)
    write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"),pe.OPTIONAL_HEADER.SizeOfCode+raw_size)
    write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"),align(new+len(blob),pe.OPTIONAL_HEADER.SectionAlignment))
    write("<II",pe.OPTIONAL_HEADER.DATA_DIRECTORY[1].get_file_offset(),new+import_at,len(imports))
    write("<II",pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].get_file_offset(),new+table_at,len(rows)*12)
    result[padding_at:padding_at+len(iat)] = iat; allowed.update(range(padding_at,padding_at+len(iat)))
    write("<I",rdata.get_field_absolute_offset("Misc_VirtualSize"),iat_offset+len(iat))
    write("<II",original_iat.get_file_offset(),original_iat.VirtualAddress,iat_offset+len(iat))
    write("<II",pe.OPTIONAL_HEADER.DATA_DIRECTORY[11].get_file_offset(),0,0)
    write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"),0)
    result.extend(blob.ljust(raw_size,b"\0")); check = pefile.PE(data=bytes(result))
    write("<I",check.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"),check.generate_checksum()); check.close()
    check = pefile.PE(data=bytes(result))
    require([(r.struct.BeginAddress,r.struct.EndAddress,r.struct.UnwindData) for r in check.DIRECTORY_ENTRY_EXCEPTION] == rows,
            "Reparsed exception table differs")
    require(check.get_data(PROCESS,len(PROCESS_PREFIX)) == PROCESS_PREFIX, "Original queue drain changed")
    require([(r.dll,[(i.name,i.address-pe.OPTIONAL_HEADER.ImageBase) for i in r.imports]) for r in pe.DIRECTORY_ENTRY_IMPORT] ==
            [(r.dll,[(i.name,i.address-check.OPTIONAL_HEADER.ImageBase) for i in r.imports]) for r in check.DIRECTORY_ENTRY_IMPORT[:len(old_imports)]],
            "Original import rows changed")
    require(len(check.DIRECTORY_ENTRY_IMPORT) == len(old_imports)+2, "Helper dependency count differs")
    require(all(i in allowed for i,(a,b) in enumerate(zip(source,result)) if a != b), "Unexpected existing-byte mutation")
    require(all(s.Characteristics & 0xa0000000 != 0xa0000000 for s in check.sections), "RWX section forbidden")
    final_iat = check.OPTIONAL_HEADER.DATA_DIRECTORY[12]
    require((final_iat.VirtualAddress,final_iat.Size) == (0x1dd2000,0x69a478), "Loader IAT protection coverage differs")
    require(source[rdata.PointerToRawData:rdata.PointerToRawData+0x790] == result[rdata.PointerToRawData:rdata.PointerToRawData+0x790],
            "Original IAT bytes changed")
    for row in check.DIRECTORY_ENTRY_IMPORT:
        require(final_iat.VirtualAddress <= row.struct.FirstThunk and
                row.struct.FirstThunk+(len(row.imports)+1)*8 <= final_iat.VirtualAddress+final_iat.Size,
                "IAT lies outside Windows loader protection directory")
    md = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    body = check.get_data(generated[0],generated[1]-generated[0]); decoded = list(md.disasm(body,generated[0]))
    require(sum(i.size for i in decoded) == len(body), "Incomplete queue wrapper disassembly")
    report = dict(source_sha256=sha(source),output_sha256=sha(result),patches=patches,original_runtime_rows=len(oldrows),
                  generated_runtime_row=[hex(v) for v in generated],unwind_bytes=unwind.hex(),
                  original_imports_preserved=True,imports_added=["NebulaNetworkBridge.dll","NebulaPublicAccess.dll"],
                  existing_mutations_allowlisted=True,iat_size=hex(final_iat.Size),
                  queue_wrapper=[f"{i.address:x}: {i.mnemonic} {i.op_str}" for i in decoded],
                  installed=False,game_launched=False,native_runtime_accepted=False)
    check.close();pe.close();return bytes(result),report
