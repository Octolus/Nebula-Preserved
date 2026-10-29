"""IAT-corrected v2 atomic, offline-only PE composition for the exact reviewed layered client.

Preserves all existing PE imports/runtime functions and adds auth69, movement4,
economy2 together. No arbitrary RVA input, installation, or target execution.
Requires a final independently reviewed helper/hash input plan. No default pin.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import capstone
from capstone import x86_const as x86
import pefile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SOURCE="8460554e5287fe8e3c5fe475f65379da971bcccf2f21f716f2ca82d6e029b9fd"
COFF_PIN="6a65a9eab4340d759a5fc7509622b2fd741bae473fc8a954cadd7d7cb24ffdee"
GET_PIN="3701dd476b1f8085807a4cef4f49e604455c1324641a843862731e7f60ffae94"
ECONOMY_PIN="ede3f026cab87cd905ae2368efd302082bde4562961ab9efc658cdf4932640e0"
MOVEMENT_PIN="80c1f3d0798faaa3b2659ec4cca4c81651c435ebaf1cc471d301e0eee5951504"
MOVE=((0x612f35,"e806670900","MovementMoveV"),(0x612f57,"e874660900","MovementMoveH"),(0x61318f,"e8ac640900","MovementRotateV"),(0x6131b0,"e81b640900","MovementRotateH"))
ECONOMY=((0x410d10,"Shop","NebulaAutomation_EconomyShopInfoCompleted"),(0x634fb0,"Purchases","NebulaAutomation_EconomyPurchasesCompleted"))
AUTOMATION_IMPORTS={"bcrypt.dll","kernel32.dll"}|{f"api-ms-win-crt-{name}-l1-1-0.dll" for name in ("convert","heap","locale","private","runtime","stdio","string")}
PUBLIC_IMPORTS={"bcrypt.dll","crypt32.dll","kernel32.dll"}|{f"api-ms-win-crt-{name}-l1-1-0.dll" for name in ("convert","environment","filesystem","heap","locale","private","runtime","stdio","string","utility")}
sha=lambda b:hashlib.sha256(b).hexdigest()
align=lambda n,a:(n+a-1)//a*a
def require(ok,message):
    if not ok:raise ValueError(message)
def read(path,pin):
    b=Path(path).read_bytes();require(sha(b)==pin,"Pinned input differs: "+str(path));return b
def module(path,pin):
    read(path,pin);spec=importlib.util.spec_from_file_location("pinned_coff_reader",path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def stolen(source,pe,rva):
    """Exact two reviewed entry prologues; no generic stolen-instruction API.

    Both begin `40 53` (push rbx), `48 83 ec 20` (sub rsp,32).
    Stop before the RIP-relative cmp at +6. A trampoline receives its own
    precise unwind row: PUSH_NONVOL at +2, ALLOC_SMALL at +6, no handler.
    """
    require(rva in (0x410d10,0x634fb0),"Unapproved entry trampoline")
    offset=pe.get_offset_from_rva(rva);raw=source[offset:offset+6]
    require(raw==bytes.fromhex("40534883ec20"),"Exact economy prologue bytes changed")
    md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    require([(i.mnemonic,i.op_str,i.size)for i in md.disasm(raw,rva)]==[("push","rbx",2),("sub","rsp, 0x20",4)],"Economy prologue instruction boundaries changed")
    rows=[row.struct for row in pe.DIRECTORY_ENTRY_EXCEPTION if row.struct.BeginAddress==rva]
    require(len(rows)==1,"Entry has no unique original runtime function")
    original=pe.get_data(rows[0].UnwindData,4)
    require(len(original)==4 and original[0]==1,"Handler/chained original unwind not supported by entry trampoline recipe")
    return raw,[(2,".seh_pushreg %rbx"),(6,".seh_stackalloc 0x20")]

def assembly(prologues):
    lines=[".text",".extern IatPublicGet",".extern IatShop",".extern IatPurchases",".extern ResumeShop",".extern ResumePurchases",
           ".global PublicGetThunk","PublicGetThunk:","    jmp *IatPublicGet(%rip)"]
    for name,(raw,unwind) in prologues.items():
        lines += [".p2align 4",f".global Economy{name}",f".seh_proc Economy{name}",f"Economy{name}:","    subq $0x48,%rsp","    .seh_stackalloc 0x48","    .seh_endprologue","    movq %rcx,0x20(%rsp)","    movq %rdx,0x28(%rsp)","    movq %r8,0x30(%rsp)","    movq %r9,0x38(%rsp)",f"    call Trampoline{name}","    movq 0x28(%rsp),%rcx",f"    call *Iat{name}(%rip)","    addq $0x48,%rsp","    ret",".seh_endproc",
                  ".p2align 4",f".global Trampoline{name}",f".seh_proc Trampoline{name}",f"Trampoline{name}:"]
        previous=0
        for end,directive in unwind:
            lines += ["    .byte "+",".join(hex(b)for b in raw[previous:end]),"    "+directive]
            previous=end
        require(previous==len(raw),"Unwind instructions do not cover trampoline prologue")
        lines += ["    .seh_endprologue",f"    jmp Resume{name}",".seh_endproc"]
    return "\n".join(lines)+"\n"

def exports(data,required,expected_imports):
    pe=pefile.PE(data=data);require(pe.FILE_HEADER.Machine==0x8664 and pe.OPTIONAL_HEADER.Magic==0x20b,"AMD64 helper required")
    names={s.name.decode("ascii") for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name};require(set(required)<=names,"Final helper missing composition exports")
    require(all(x.forwarder is None for x in pe.DIRECTORY_ENTRY_EXPORT.symbols if x.name and x.name.decode("ascii") in required),"Forwarded composition exports rejected")
    imports={r.dll.decode("ascii").lower() for r in pe.DIRECTORY_ENTRY_IMPORT}
    require(imports==expected_imports,"Helper dependency set differs from exact reviewed system-only closure")
    require(not pe.OPTIONAL_HEADER.DATA_DIRECTORY[13].Size,"Unexpected delay-loaded helper dependency")
    return pe

def compose(args):
    plan=json.loads(Path(args.plan).read_text(encoding="utf-8"));require(plan.get("format")=="nebula-pe-input-v1" and plan.get("status") in ("final-helper-reviewed","profile-handshake"),"Missing independently reviewed helper input/profile handshake")
    require(plan.get("review") and not plan["review"].startswith("PENDING"),"Pending helper review")
    source=read(plan["source"],SOURCE)
    automation=read(plan["automation"],plan["automation_sha256"]);public=read(plan["public_access"],plan["public_access_sha256"])
    exports(automation,["NebulaAutomation_Pump","NebulaAutomation_MovementAxis"]+[e[2] for e in ECONOMY],AUTOMATION_IMPORTS);exports(public,["NebulaPublicAccess_AbiVersion","NebulaPublicAccess_Get"],PUBLIC_IMPORTS)
    coff=module(ROOT/"recipes/interaction_registry_patch.py",COFF_PIN).coff
    calls=json.loads(read(HERE/"unitywebrequest-get-calls.json",GET_PIN))
    contract=json.loads(read(HERE/"economy-callback-hooks.json",ECONOMY_PIN))
    require(contract["gameassembly_base_sha256"]==SOURCE and [(int(h["rva"],16),h["after_original_export"])for h in contract["hooks"]]==[(r,e)for r,_,e in ECONOMY],"Economy contract drift")
    require(calls["source_binary_sha256"]==SOURCE and calls["direct_call_count"]==69 and len(calls["calls"])==69 and len({c["call_rva"] for c in calls["calls"]})==69 and calls["get_send_caller_sets_equal"] is True,"Auth Get/Send source-bound coverage differs")
    pe=pefile.PE(data=source);require(pe.FILE_HEADER.Machine==0x8664 and pe.OPTIONAL_HEADER.Magic==0x20b,"AMD64 PE32+ required")
    require(not pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size and pe.get_overlay_data_start_offset() is None,"Signed/overlay source rejected")
    last=pe.sections[-1];require(last.Name.rstrip(b"\0")==b".nbi" and last.Characteristics==0x60000020 and last.PointerToRawData+last.SizeOfRawData==len(source),"Reviewed terminal RX section required")
    for row in calls["calls"]:
        rva=int(row["call_rva"],16);off=pe.get_offset_from_rva(rva);original=bytes.fromhex(row["original_hex"])
        require(off==int(row["file_offset"],16) and len(original)==5 and original[0]==0xe8 and source[off:off+5]==original and rva+5+struct.unpack_from("<i",original,1)[0]==0x1d9b350,"Auth callsite original bytes/target mismatch")
    prologues={name:stolen(source,pe,rva)for rva,name,_ in ECONOMY}
    out=Path(args.output).resolve();require(not out.exists() and "steamapps" not in [p.lower() for p in out.parts],"Output must be new isolated path outside Steam")
    require(not out.is_relative_to(ROOT),"Build output must be outside the source tree")
    out.mkdir(parents=True);asm=out/"core_wrappers.s";asm.write_text(assembly(prologues),encoding="ascii");obj=out/"core_wrappers.o"
    cc=Path(args.cc or shutil.which("x86_64-w64-mingw32-gcc") or "");require(cc.is_file(),"Mingw AMD64 assembler required")
    process=subprocess.run([str(cc),"-c",str(asm),"-o",str(obj)],capture_output=True,text=True);require(process.returncode==0,"Wrapper assembly failed: "+process.stderr)
    movement_source=HERE/"movement_shims.s"
    read(movement_source,"be9e47a9a26e8b2caa441f1ac5afb37437fa7c095a8ede87265b97adec6262f7")
    movement_object=out/"movement_shims.o"
    process=subprocess.run([str(cc),"-c",str(movement_source),"-o",str(movement_object)],capture_output=True,text=True)
    require(process.returncode==0,"Movement assembly failed: "+process.stderr)
    objects=[coff(obj.read_bytes()),coff(read(movement_object,MOVEMENT_PIN))]
    # Build new imports in the same final section; Windows loader resolves pinned sibling DLLs once.
    new=last.VirtualAddress+last.SizeOfRawData;blob=bytearray();runtime=[];public_symbols={};relocations=[];section_specs=[]
    for sections,symbols in objects:
        sec={s["name"]:s for s in sections};require(set(sec)=={".text",".data",".bss",".xdata",".pdata"} and not sec[".data"]["data"] and not sec[".bss"]["data"] and not sec[".xdata"]["relocs"],"Unexpected COFF contents")
        names={i+1:s["name"]for i,s in enumerate(sections)};code_at=align(len(blob),16);blob.extend(bytes(code_at-len(blob)));code=sec[".text"]["data"];blob.extend(code);xat=align(len(blob),4);blob.extend(bytes(xat-len(blob)));blob.extend(sec[".xdata"]["data"])
        for symbol in symbols.values():
            if names.get(symbol["section"])==".text" and symbol["storage"]==2:require(symbol["name"] not in public_symbols,"Duplicate public wrapper");public_symbols[symbol["name"]]=new+code_at+symbol["value"]
        for offset,symbol,kind in sec[".text"]["relocs"]:relocations.append((code_at+offset,symbol,kind,names,code_at,xat))
        pdata=sec[".pdata"]["data"]
        for offset,symbol,kind in sec[".pdata"]["relocs"]:
            require(kind==3 and names.get(symbol["section"])in(".text",".xdata"),"Unsupported pdata relocation")
            base=new+(code_at if names[symbol["section"]]==".text" else xat);value=struct.unpack_from("<I",pdata,offset)[0];struct.pack_into("<I",pdata,offset,base+symbol["value"]+value)
        require(len(pdata)%12==0,"Malformed generated pdata");runtime.extend(struct.iter_unpack("<III",pdata));section_specs.append({"code_rva":hex(new+code_at),"code_size":len(code),"xdata_rva":hex(new+xat)})
    require(len(runtime)==8,"Expected four movement wrappers, two economy wrappers and two economy trampolines")
    # Import descriptor table preserves exact old descriptors and their old IAT/INTs.
    directory=pe.OPTIONAL_HEADER.DATA_DIRECTORY[1];old_imports=[]
    for row in pe.DIRECTORY_ENTRY_IMPORT:old_imports.append(source[row.struct.get_file_offset():row.struct.get_file_offset()+20])
    require(all(row.dll.lower() not in (b"nebulaautomation.dll",b"nebulapublicaccess.dll") for row in pe.DIRECTORY_ENTRY_IMPORT),"Duplicate helper import")
    rdata=[section for section in pe.sections if section.Name.rstrip(b"\0")==b".rdata"]
    require(len(rdata)==1,"Unique reviewed rdata section required");rdata=rdata[0]
    require(rdata.VirtualAddress==0x1dd2000 and rdata.Misc_VirtualSize==0x69a456 and rdata.SizeOfRawData==0x69a600 and rdata.Characteristics==0x40000040,"Reviewed read-only rdata profile differs")
    original_iat=pe.OPTIONAL_HEADER.DATA_DIRECTORY[12]
    require((original_iat.VirtualAddress,original_iat.Size)==(0x1dd2000,0x790),"Reviewed original IAT directory differs")
    iat_offset=align(rdata.Misc_VirtualSize,8);iat_bytes=bytearray()
    require(iat_offset==0x69a458 and iat_offset+40<=rdata.SizeOfRawData,"Insufficient reviewed rdata padding")
    padding_at=rdata.PointerToRawData+iat_offset
    require(not any(source[padding_at:padding_at+40]),"New IAT padding is not pristine zero")
    imports=[];targets={"OriginalVertical":0x6a9640,"OriginalHorizontal":0x6a95d0,"IatGetModuleHandleW":0x1dd20b8,"IatGetProcAddress":0x1dd20c0}
    for dll,entries in [("NebulaAutomation.dll",[("IatShop",ECONOMY[0][2]),("IatPurchases",ECONOMY[1][2])]),("NebulaPublicAccess.dll",[("IatPublicGet","NebulaPublicAccess_Get")])]:
        name_rva=new+len(blob);blob.extend(dll.encode()+b"\0");hints=[]
        for key,export in entries:
            blob.extend(bytes(align(len(blob),2)-len(blob)));hints.append(new+len(blob));blob.extend(b"\0\0"+export.encode()+b"\0")
        blob.extend(bytes(align(len(blob),8)-len(blob)));int_rva=new+len(blob);thunks=b"".join(struct.pack("<Q",h)for h in hints)+bytes(8);blob.extend(thunks);iat_rva=rdata.VirtualAddress+iat_offset+len(iat_bytes);iat_bytes.extend(thunks)
        for i,(key,_)in enumerate(entries):targets[key]=iat_rva+i*8
        imports.append(struct.pack("<IIIII",int_rva,0,0,name_rva,iat_rva))
    for rva,name,_ in ECONOMY:targets["Resume"+name]=rva+len(prologues[name][0])
    for offset,symbol,kind,names,code_at,xat in relocations:
        require(kind==4,"Only REL32 code relocations supported")
        if symbol["section"]>0:
            require(names[symbol["section"]]==".text","Code relocation outside text");target=new+code_at+symbol["value"]
        else:require(symbol["name"]in targets,"Unapproved external relocation: "+symbol["name"]);target=targets[symbol["name"]]
        old=struct.unpack_from("<i",blob,offset)[0];struct.pack_into("<i",blob,offset,target+old-(new+offset+4))
    require(len(iat_bytes)==40,"Expected exactly five new 64-bit IAT words including terminators")
    import_at=align(len(blob),4);blob.extend(bytes(import_at-len(blob)));import_table=b"".join(old_imports+imports)+bytes(20);blob.extend(import_table)
    old_exception=pe.OPTIONAL_HEADER.DATA_DIRECTORY[3];oldrows=list(struct.iter_unpack("<III",pe.get_data(old_exception.VirtualAddress,old_exception.Size)));require(oldrows==sorted(oldrows),"Old exception rows not ordered")
    rows=sorted(oldrows+runtime);require(all(a<b for a,b,_ in rows) and all(rows[i][1]<=rows[i+1][0]for i in range(len(rows)-1)),"Runtime functions overlap")
    md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    for begin,end,unwind in runtime:
        require(new<=begin<end<=new+len(blob) and new<=unwind<new+len(blob),"Generated runtime bounds invalid")
        code=bytes(blob[begin-new:end-new]);ins=list(md.disasm(code,begin));require(ins and sum(x.size for x in ins)==len(code) and ins[-1].mnemonic in("ret","jmp"),"Incomplete generated wrapper disassembly")
        u=unwind-new;require(blob[u]&7==1 and blob[u]>>3==0,"Unexpected generated unwind flags")
    table_at=align(len(blob),4);blob.extend(bytes(table_at-len(blob)));table=b"".join(struct.pack("<III",*r)for r in rows);blob.extend(table)
    result=bytearray(source);allowed=set();patches=[]
    def write(fmt,at,*values):struct.pack_into(fmt,result,at,*values);allowed.update(range(at,at+struct.calcsize(fmt)))
    def patch(rva,before,target,opcode,name):
        off=pe.get_offset_from_rva(rva);require(source[off:off+len(before)]==before,"Original patch bytes mismatch")
        after=bytes([opcode])+struct.pack("<i",target-rva-5)+b"\x90"*(len(before)-5);require(len(after)==len(before),"Invalid patch width")
        result[off:off+len(after)]=after;allowed.update(range(off,off+len(after)));patches.append({"name":name,"rva":hex(rva),"before":before.hex(),"after":after.hex(),"target":hex(target)})
    for c in calls["calls"]:patch(int(c["call_rva"],16),bytes.fromhex(c["original_hex"]),public_symbols["PublicGetThunk"],0xe8,"HTTPS.Get")
    for rva,before,name in MOVE:patch(rva,bytes.fromhex(before),public_symbols[name],0xe8,name)
    for rva,name,_ in ECONOMY:patch(rva,prologues[name][0],public_symbols["Economy"+name],0xe9,"Economy"+name)
    size=align(len(blob),pe.OPTIONAL_HEADER.FileAlignment)
    write("<I",last.get_field_absolute_offset("Misc_VirtualSize"),last.SizeOfRawData+len(blob));write("<I",last.get_field_absolute_offset("SizeOfRawData"),last.SizeOfRawData+size)
    write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfCode"),pe.OPTIONAL_HEADER.SizeOfCode+size);write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"),align(new+len(blob),pe.OPTIONAL_HEADER.SectionAlignment))
    write("<II",directory.get_file_offset(),new+import_at,len(import_table));write("<II",old_exception.get_file_offset(),new+table_at,len(table))
    # Both old and new IATs must be writable during loader snapping. Preserve
    # original IAT start, cover only one homogeneous read-only rdata section,
    # and place all new IATs in verified unused raw padding. Never span RX/data.
    result[padding_at:padding_at+len(iat_bytes)]=iat_bytes;allowed.update(range(padding_at,padding_at+len(iat_bytes)))
    expanded_iat_end=rdata.VirtualAddress+iat_offset+len(iat_bytes)
    require(expanded_iat_end==0x246c480 and expanded_iat_end<=rdata.VirtualAddress+rdata.SizeOfRawData,"Expanded IAT leaves read-only rdata")
    write("<I",rdata.get_field_absolute_offset("Misc_VirtualSize"),iat_offset+len(iat_bytes))
    write("<II",original_iat.get_file_offset(),original_iat.VirtualAddress,expanded_iat_end-original_iat.VirtualAddress)
    write("<II",pe.OPTIONAL_HEADER.DATA_DIRECTORY[11].get_file_offset(),0,0)
    write("<I",pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"),0);result.extend(blob.ljust(size,b"\0"));check=pefile.PE(data=bytes(result));write("<I",check.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum"),check.generate_checksum());check=pefile.PE(data=bytes(result))
    require([(x.struct.BeginAddress,x.struct.EndAddress,x.struct.UnwindData)for x in check.DIRECTORY_ENTRY_EXCEPTION]==rows,"Reparsed exception table mismatch")
    require(len(check.sections)==len(pe.sections) and len(check.DIRECTORY_ENTRY_IMPORT)==len(old_imports)+2,"Reparsed import/section mismatch")
    require(all(i in allowed for i,(a,b)in enumerate(zip(source,result))if a!=b),"Unexplained old-byte mutation")
    require(len(patches)==75,"All75 fixed hooks must compose together")
    checked_rdata=next(section for section in check.sections if section.Name.rstrip(b"\0")==b".rdata")
    checked_iat=check.OPTIONAL_HEADER.DATA_DIRECTORY[12]
    require((checked_iat.VirtualAddress,checked_iat.Size)==(0x1dd2000,0x69a480),"Reparsed loader IAT coverage mismatch")
    require(checked_rdata.Characteristics==0x40000040 and checked_rdata.Misc_VirtualSize==0x69a480,"Reparsed rdata permissions/extent changed")
    require(source[rdata.PointerToRawData:rdata.PointerToRawData+0x790]==result[rdata.PointerToRawData:rdata.PointerToRawData+0x790],"Original IAT bytes changed")
    for descriptor in check.DIRECTORY_ENTRY_IMPORT:
        require(checked_iat.VirtualAddress<=descriptor.struct.FirstThunk and descriptor.struct.FirstThunk+(len(descriptor.imports)+1)*8<=checked_iat.VirtualAddress+checked_iat.Size,"Import IAT is not fully covered by loader protection directory")
    require(all(section.Characteristics&0xa0000000!=0xa0000000 for section in check.sections),"RWX section introduced")
    output=bytes(result)
    if plan["status"]=="final-helper-reviewed":require(plan.get("expected_output_sha256")==sha(output),"Final composition must reproduce independently reviewed handshake GA SHA256")
    (out/"GameAssembly.dll").write_bytes(output)
    report={"format":"nebula-pe-composition-v1","status":plan["status"],"source_sha256":SOURCE,"output_sha256":sha(output),"automation_sha256":sha(automation),"public_access_sha256":sha(public),"input_plan_sha256":sha(Path(args.plan).read_bytes()),"composer_sha256":sha(Path(__file__).read_bytes()),"compiler_sha256":sha(cc.read_bytes()),"wrapper_source_sha256":sha(asm.read_bytes()),"wrapper_object_sha256":sha(obj.read_bytes()),"movement_object_sha256":MOVEMENT_PIN,"get_inventory_sha256":GET_PIN,"economy_contract_sha256":ECONOMY_PIN,"patches":patches,"runtime_functions_added":len(runtime),"runtime_functions_preserved":len(oldrows),"imports_added":["NebulaAutomation.dll","NebulaPublicAccess.dll"],"section_specs":section_specs,"original_byte_mutations_allowlisted":True,"iat_correction":{"original_start":"0x1dd2000","original_size":"0x790","expanded_size":"0x69a480","new_iat_start":"0x246c458","new_iat_end":"0x246c480","rdata_characteristics":"0x40000040","original_iat_bytes_preserved":True,"every_import_iat_covered":True,"homogeneous_readonly_section_only":True},"executed":False,"installed":False,"runtime_acceptance_pending":True}
    (out/"composition-receipt.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8");print(json.dumps({"output_sha256":sha(output),"hooks":len(patches),"executed":False}))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--plan",required=True);parser.add_argument("--output",required=True);parser.add_argument("--cc");compose(parser.parse_args())
