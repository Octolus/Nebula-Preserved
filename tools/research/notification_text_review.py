"""Independent static notification-wrapper audit; no target execution.

Rebuilds candidate PE bytes in memory only and decodes bytes with Capstone.
Never invokes the patcher's CLI or its instruction-model test harness.
"""

from _research_paths import workspace, output_root, game_path
from pathlib import Path
import hashlib
import importlib.util
import json
import struct

import capstone
import pefile

ROOT = workspace()
BASE = ROOT / "results"
OUT = BASE / "protocol"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(instruction):
    return {"rva":hex(instruction.address),"bytes":instruction.bytes.hex(),
            "mnemonic":instruction.mnemonic,"operands":instruction.op_str}


def exception_rows(pe):
    pe.parse_data_directories(directories=[3])
    return [(x.struct.BeginAddress,x.struct.EndAddress,x.struct.UnwindData) for x in pe.DIRECTORY_ENTRY_EXCEPTION]


def main():
    patcher_path = BASE / "tools/notification_text_patch.py"
    patch = load("notification_text_patch_reviewed", patcher_path)
    rapid_manifest = json.loads((BASE / "client-fixes/prepared-rapid-copy.json").read_text(encoding="utf-8"))
    manifest_path = BASE / "client-fixes/prepared-notification-copy.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = Path(rapid_manifest["copy_path"])
    candidate_path = Path(manifest["copy_path"])
    object_path = ROOT / "work/evidence/notification_text.o"
    original_path = ROOT / "work/evidence/GameAssembly.dll"
    source, obj = source_path.read_bytes(), object_path.read_bytes()
    original = original_path.read_bytes()
    rebuilt, rebuilt_spec = patch.build(source,obj)
    candidate = candidate_path.read_bytes()
    assert sha(original) == "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac"
    assert sha(source) == rapid_manifest["copy_sha256"] == patch.SOURCE_SHA256
    assert rebuilt == candidate and sha(rebuilt) == manifest["copy_sha256"]

    orig_pe = pefile.PE(data=original,fast_load=True)
    before = pefile.PE(data=source,fast_load=True)
    after = pefile.PE(data=rebuilt,fast_load=True)
    md = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.detail = True
    native = list(md.disasm(orig_pe.get_data(0x477470,0x477a07-0x477470),0x477470))
    assert native[-1].address == 0x477a02 and native[-1].mnemonic == "call" and native[-1].operands[0].imm == 0x13685a0
    rdi_family = {capstone.x86.X86_REG_RDI,capstone.x86.X86_REG_EDI,capstone.x86.X86_REG_DI,capstone.x86.X86_REG_DIL}
    rdi_writes = [x for x in native if rdi_family.intersection(x.regs_access()[1])]
    assert len(rdi_writes)==1 and rdi_writes[0].address==0x47748a and rdi_writes[0].op_str=="rdi, rcx"
    arg_setup = [x for x in native if 0x4779e9<=x.address<=0x477a02]
    assert [x.op_str for x in arg_setup] == [
        "rcx, qword ptr [rip + 0x2066eb8]", "r9, rsi", "r8, rax", "qword ptr [rsp + 0x20], 0", "rdx, r15", "0x13685a0"]
    assert before.get_data(0x477470,0x477a07-0x477470)==orig_pe.get_data(0x477470,0x477a07-0x477470)

    section = next(x for x in after.sections if x.Name.rstrip(b"\0")==b".nbn")
    start = section.VirtualAddress
    end = manifest["new_section"]["code_bytes"]
    instructions = list(md.disasm(after.get_data(start,end),start))
    assert sum(x.size for x in instructions)==end==144
    calls = [x for x in instructions if x.mnemonic=="call"]
    assert [x.operands[0].imm for x in calls]==[0x1365160,0x13685a0]
    rip = []
    for ins in instructions:
        for operand in ins.operands:
            if operand.type==capstone.x86.X86_OP_MEM and operand.mem.base==capstone.x86.X86_REG_RIP:
                rip.append(ins.address+ins.size+operand.mem.disp)
    assert rip==[0x24f7d08,0x2515838,0x2530b68]
    assert [x.op_str for x in instructions[:5]]==["rbx","rsi","rdi","r12","r13"]
    assert instructions[5].mnemonic=="sub" and instructions[5].op_str=="rsp, 0x30"
    assert [x.op_str for x in instructions[-7:]]==["rsp, 0x30","r13","r12","rdi","rsi","rbx",""]
    assert instructions[-7].mnemonic=="add" and instructions[-1].mnemonic=="ret"
    assert not any(x.mnemonic.startswith(("movap","movup","vmov")) for x in instructions)
    fifth = [x for x in instructions if x.mnemonic=="mov" and x.op_str=="qword ptr [rsp + 0x20], 0"]
    assert len(fifth)==1 and fifth[0].address<calls[-1].address

    old_rows,new_rows = exception_rows(before),exception_rows(after)
    new_function = tuple(int(x,16) for x in manifest["unwind"]["runtime_function"])
    assert new_rows==sorted(old_rows+[new_function]) and len(new_rows)==len(old_rows)+1
    rapid_function = tuple(int(x,16) for x in rapid_manifest["unwind"]["runtime_function"])
    assert rapid_function in old_rows and rapid_function in new_rows
    old_sections=[]
    for old in before.sections:
        matched=next(x for x in after.sections if x.Name==old.Name)
        assert old.__pack__()==matched.__pack__()
        a,b=old.get_data(),matched.get_data()
        diffs=[i for i,(left,right) in enumerate(zip(a,b)) if left!=right]
        if old.VirtualAddress<=0x477a02<old.VirtualAddress+old.Misc_VirtualSize:
            redirect=0x477a02-old.VirtualAddress
            assert all(redirect<=i<redirect+5 for i in diffs)
        else:
            assert a==b
        old_sections.append({"name":old.Name.rstrip(b"\0").decode(),"header_identical":True,
                             "original_data_identical":a==b,"changed_offsets":diffs})
    assert section.Characteristics==0x60000020
    assert after.OPTIONAL_HEADER.ImageBase==before.OPTIONAL_HEADER.ImageBase
    # Base-relocation/import/other loader directories must be byte-identical;
    # only the exception-directory entry is redirected to the expanded table.
    for index,(a,b) in enumerate(zip(before.OPTIONAL_HEADER.DATA_DIRECTORY,after.OPTIONAL_HEADER.DATA_DIRECTORY)):
        if index!=3: assert a.__pack__()==b.__pack__()
    unwind_rva=new_function[2]
    xdata=after.get_data(unwind_rva,16)
    assert xdata[:16].hex()=="010b06000b5207d005c0037002600130"
    assert new_function==(start,start+144,start+144)
    assert after.verify_checksum()

    class GuardError(Exception): pass
    class Parser:
        def error(self,message): raise GuardError(message)
    parser=Parser()
    guard_checks=[]
    protected={source_path.resolve(),object_path.resolve(),patch.ASM.resolve()}
    tests=[("existing source",source_path,None),("existing object",object_path,None),
           ("assembly source",patch.ASM,None),("existing prepared JSON",manifest_path,".json"),
           ("existing patcher",patcher_path,None),
           ("Steam path",game_path('never-created-review.json'),".json"),
           ("invalid JSON suffix",ROOT/"work/never-created-notification-review.bin",".json")]
    for label,path,suffix in tests:
        try: patch.safe_new_path(parser,path,protected,label,suffix)
        except GuardError: guard_checks.append({"case":label,"rejected":True})
        else: raise AssertionError("Guard unexpectedly permitted "+label)
    alias=ROOT/"work/never-created-notification-output.json"
    try: patch.safe_new_path(parser,alias,protected|{alias.resolve()},"same destination/report",".json")
    except GuardError: guard_checks.append({"case":"same destination/report","rejected":True})
    else: raise AssertionError("Destination/report alias not rejected")

    literal_data=json.loads((ROOT/"work/decompiled/stringliteral.json").read_text(encoding="utf-8-sig"))
    literal_map={int(x["address"],16):x["value"] for x in literal_data}
    literals={hex(rva):literal_map[rva] for rva in rip}
    sources=[Path(__file__),patcher_path,BASE/"tools/notification_text_offline_tests.py",patch.ASM,object_path,
             manifest_path,BASE/"protocol/notification-text-compatibility.json",
             ROOT/"work/evidence/ghidra/functions/477470.c",ROOT/"work/evidence/ghidra/functions/610d40.c",
             ROOT/"work/decompiled/dump.cs",ROOT/"work/evidence/notification-text-offline-tests.json",
             BASE/"client-fixes/notification-text-offline-tests.json"]
    assert (ROOT/"work/evidence/notification-text-offline-tests.json").read_bytes()==(BASE/"client-fixes/notification-text-offline-tests.json").read_bytes()
    report={
        "format_version":1,"review_type":"independent static review and in-memory PE rebuild",
        "target_executed":False,"instruction_model_executed_by_reviewer":False,
        "native_helpers_executed":False,"game_or_ui_started":False,"listeners_or_connections":False,
        "installation_changed":False,"new_candidate_written_by_reviewer":False,
        "verdict":"no concrete native ABI, field-layout, relocation or PE preservation defect found in reviewed bytes; runtime validation remains unavailable",
        "source_sha256":sha(source),"candidate_sha256":sha(rebuilt),"candidate_matches_prepared_copy":True,
        "original_binary_sha256":sha(original),
        "rdi_proof":{"assignment":row(rdi_writes[0]),"other_rdi_writes_before_redirect":0,"preserved_across_original_calls":"Win64 nonvolatile ABI"},
        "original_argument_setup":[row(x) for x in arg_setup],
        "wrapper_disassembly":[row(x) for x in instructions],
        "field_layout":{"ChatEntry_nullable":hex(0x108),"nullable_hasValue":hex(0x108),"type":hex(0x110),
                        "arguments":hex(0x130),"Il2CppString_length":hex(0x10)},
        "abi":{"entry_rsp_mod16":8,"five_pushes_bytes":40,"allocation_bytes":48,"frame_bytes":88,
               "precall_rsp_mod16":0,"callee_entry_rsp_mod16":8,"shadow_bytes":32,
               "format_fifth_parameter":"zero at caller RSP+0x20 -> callee RSP+0x28",
               "concat_MethodInfo":"zero R9", "nonvolatile_preserved":["RBX","RSI","RDI","R12","R13"],
               "other_nonvolatile":"RBP/R14/R15 and XMM6..15 are not modified"},
        "literal_slots":literals,"calls":[row(x) for x in calls],
        "unwind":{"raw_hex":xdata.hex(),"prologue_bytes":11,"codes":"allocate48 at11;pushR13at7;pushR12at5;pushRDIat3;pushRSIat2;pushRBXat1", "function":list(new_function)},
        "pe":{"old_runtime_functions":len(old_rows),"new_runtime_functions":len(new_rows),"all_old_rows_identical":True,
              "rapid_wrapper_row_preserved":list(rapid_function),"old_sections":old_sections,
              "loader_directories_except_exception_unchanged":True,"new_section_RX":True,
              "absolute_pointer_relocations_added":False,"signed_rel32_targets_in_range":True},
        "path_guards":guard_checks,
        "gc_assessment":{"heap_reference_field_writes_added":False,"new_managed_roots":"original references retained in nonvolatile registers; Concat RAX immediately retained in R13 before Format",
                         "basis":"matches native nonvolatile-register managed-reference lifetime pattern; no unmanaged buffer or unrooted allocation interval added",
                         "proven_runtime_collector_behavior":False},
        "findings":[],
        "resolved_observations":[{"category":"documentation","file":"protocol/notification-text-compatibility.json",
                     "correction":"Parent narrowed exclusion wording to unrelated gameplay/UI behavior and explicitly states intended notification text changes before final source hashing"}],
        "remaining_risks":["Unity/IL2CPP GC collection and managed helper exceptions are not tested", "Windows loader and exception unwinding are not executed",
                           "Visual presentation is not observed", "Native field/register offsets are valid only for this exact build",
                           "Synthetic tests model helper return values and ABI poisoning; they do not establish real String/GC/rendering behavior",
                           "Path guards prevent normal aliases, existing files and steamapps outputs; concurrent malicious parent-directory replacement is not a promised threat model"],
        "sources":[{"path":str(path.relative_to(ROOT)),"sha256":sha(path.read_bytes())} for path in sources],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"notification-text-review.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    (OUT/"notification-text-review.md").write_text(markdown(report),encoding="utf-8")
    print(json.dumps({"candidate_matches":True,"old_runtime_functions_preserved":len(old_rows),
                      "guard_checks":len(guard_checks),"native_execution":False}))


def markdown(report):
    return f'''# Independent notification text patch review

No concrete native ABI, field-layout, relocation or PE preservation defect was found in the reviewed bytes. The candidate rebuilds in memory exactly to prepared SHA256 `{report["candidate_sha256"]}`. This is static review, not runtime clearance: no native code, game, UI, listener, connection or synthetic instruction model was executed by this reviewer, and no candidate copy was written or installed.

## Original call site and data layout

The original DLL contains `mov rdi,rcx` at0x47748a. Capstone register-write analysis finds no further RDI write through the final call0x477a02; intermediate calls must preserve RDI under the original Win64 ABI. The rapid+wardrobe input's entire reviewed setter byte range is identical to the original DLL. RDI therefore still holds ChatEntry at the redirect.

Immediately before the original call,0x4779e9 loads the final format into RCX,0x4779f0 copies body RSI to R9,0x4779f3 copies the colored-name RAX to R8,0x4779f6 writes zero to caller RSP+0x20, and0x4779ff copies timestamp R15 to RDX. The E8 at0x477a02 targets String.Format0x13685a0. IL2CPP declarations confirm its four managed parameters plus MethodInfo fifth argument. String.Concat0x1365160 has three managed string parameters plus MethodInfo in R9.

The nullable field starts at ChatEntry+0x108. The native setter's concrete copy establishes HasValue+0x108, NotificationData.type+0x110 and arguments+0x130; the generic Nullable declaration alone would not prove aligned payload offsets. NotificationData's own type+0/arguments+0x20 and String._stringLength+0x10 agree with the dumped declarations. There are no newly authored managed-reference field stores.

## Wrapper ABI, literals and GC exposure

The144-byte wrapper saves RBX,RSI,RDI,R12,R13 (40 bytes) and allocates0x30 (48 bytes). At entry RSP mod16=8; subtracting88 yields an aligned call site. It reserves32 bytes of shadow space and puts Format's null MethodInfo at caller RSP+0x20, which is callee-entry RSP+0x28 after the return-address push. Concat receives null MethodInfo in R9. RBP,R14,R15 and XMM6..15 are untouched. Every saved register and stack allocation is restored in the normal epilogue.

The code calls only the original Concat and Format helpers. RIP-relative reads resolve to the original initialized literal slots0x24f7d08/0x2515838/0x2530b68. The original setter initializes those slots before reaching this call site. Non-null empty body, non-null ChatEntry, HasValue and type3/4 are checked before substitution. Null/nonempty bodies and other types pass through. Gift arguments can be null because the reused managed Concat accepts null strings. The wrapper still invokes original Format for every branch.

Original format/timestamp/name/body references remain in nonvolatile registers across Concat. Its returned managed string moves directly RAX->R13 before the next allocating helper. That follows the native setter's existing register-held reference pattern and adds no unmanaged heap-reference buffer or intervening allocation. Actual collector root discovery, managed helper exceptions and Unity behavior remain untested; the instruction-model report cannot prove those properties.

## PE layout and unwind

All{report["pe"]["old_runtime_functions"]} existing runtime-function rows, including the rapid wrapper, are preserved exactly. A single new row covers0x2ca8000..0x2ca8090 and points to unwind data at0x2ca8090. The11-byte prologue and six unwind entries agree with the actual pushes/allocation. Exception dispatch was not run.

The new .nbn section is read/execute. Every old section header is identical; all old section data is identical except the redirect's four changed rel32 operand bytes in the actual `il2cpp` code section (the E8 opcode stays the same). The rapid section and its call redirect remain unchanged. All loader directories other than the moved exception-directory entry are identical. References use signed rel32/RIP-relative displacement and RVA table entries; no absolute pointer relocation is introduced. Both literal pointers and original loader relocation data remain in the old sections. The rebuilt PE checksum verifies and full bytes match the prepared candidate.

## Tool and report guards

Eight parser-only guard checks reject existing source/object/assembly/patcher/prepared-JSON paths, output under steamapps, a non-json report suffix and destination/report aliasing. Source and object resolve strictly; outputs resolve before protected/existence checks; output opens use exclusive creation. A failed report write after the DLL-copy write may leave an isolated copy without a manifest, but it does not overwrite an input. Concurrent malicious replacement of a parent directory is outside these normal-use guards.

The offline test source is a Python integer instruction model with synthetic managed helper stubs. Its recorded16 cases cover gates, ABI alignment, preservation and alternate bases, but do not call native String methods, collect managed objects, render UI or dispatch Windows exceptions. This reviewer read those tests and the report without rerunning the model.

A wording issue identified during review was corrected before final hashing: `notification-text-compatibility.json` now states that unrelated gameplay/UI behavior is excluded while the intended notification text changes. No unresolved actionable finding remains in this static review.

Source hashes, complete wrapper disassembly, call-site argument instructions, field offsets, preserved section/table details and the exact guard cases are in `notification-text-review.json`. Reproduce with `python results/tools/notification_text_review.py`; it only rebuilds PE bytes in memory and writes these review reports.
'''


if __name__=="__main__":
    main()
