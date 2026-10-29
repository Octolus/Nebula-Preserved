"""Read-only offline proof of networking-only scope and exact output closure."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import pefile
from build_network_client import ORIGINALS,REGISTRY,PUBLIC,REMOTE_PUBLIC,REMOTE_TRANSPORT,read,require,sha

HERE=Path(__file__).resolve().parent
OMITTED_SITES={
    "Cross":(0x6a8f40,5),"Circle":(0x6a8e20,5),"Square":(0x6a9b20,5),"Triangle":(0x6a9bd0,5),
    "L1":(0x6a9400,5),"R1":(0x6a9760,5),"L3":(0x6a9520,5),"R3":(0x6a98c0,5),
    "Share":(0x6a9a70,5),"Options":(0x6a96b0,5),
    "MovementV":(0x612f35,5),"MovementH":(0x612f57,5),"RotateV":(0x61318f,5),"RotateH":(0x6131b0,5),
    "ShopTelemetry":(0x410d10,6),"PurchasesTelemetry":(0x634fb0,6),"AutomationPump":(0x422e20,7),
    "NeckMale":(0x58c94a,5),"NeckFemale":(0x58df19,5),
    "EyesLeft":(0x38fb0c,25),"EyesRight":(0x38fbfa,25),"NotificationText":(0x477a02,5),
    "Cursor1":(0x6a93e0,0x1b),"Cursor2":(0x1b6b7d0,0x31),"Cursor3":(0x1b6b810,0x33),
}

def verify(original:bytes,target:bytes,receipt:dict,contract:dict):
    require(sha(original)==ORIGINALS["GameAssembly.dll"] and sha(target)==contract["ga_sha256"],"Exact original/final networking GA required")
    pe=pefile.PE(data=original);after=pefile.PE(data=target);ranges=[(0x608323,2)]
    rapid=receipt["stages"][1]["report"]["redirect"];ranges.append((int(rapid["call_rva"],16),len(bytes.fromhex(rapid["original_hex"]))))
    for stage in receipt["stages"][2:]:
        for patch in stage["report"]["patches"]:
            before=patch.get("original",patch.get("before"));ranges.append((int(patch["rva"],16),len(bytes.fromhex(before))))
    allowed=set()
    for rva,size in ranges:
        at=pe.get_offset_from_rva(rva);allowed.update(range(at,at+size))
    changes=[];executable_sections=[]
    for section in pe.sections:
        if not section.Characteristics&0x20000000:continue
        start=section.PointerToRawData;end=start+section.SizeOfRawData
        changes.extend(start+i for i,(a,b)in enumerate(zip(original[start:end],target[start:end]))if a!=b)
        executable_sections.append(section.Name.rstrip(b"\0").decode("ascii"))
    require(executable_sections and all(i in allowed for i in changes),"Non-network change in original executable text")
    preserved=[]
    for name,(rva,size)in OMITTED_SITES.items():
        require(pe.get_data(rva,size)==after.get_data(rva,size),"Optional/input/render/test site changed: "+name);preserved.append(name)
    inventory=json.loads((HERE/"pe-composition/unitywebrequest-get-calls.json").read_text())
    selected={int(row["call_rva"],16) for row in inventory["calls"]}
    def direct_calls(image,raw,wanted):
        found=set()
        for section in image.sections:
            if not section.Characteristics&0x20000000:continue
            data=raw[section.PointerToRawData:section.PointerToRawData+section.SizeOfRawData]
            at=data.find(b"\xe8")
            while at>=0:
                if at+5<=len(data):
                    rva=section.VirtualAddress+at
                    if rva+5+struct.unpack_from("<i",data,at+1)[0]==wanted:found.add(rva)
                at=data.find(b"\xe8",at+1)
        return found
    require(len(selected)==70 and 0x618467 in selected and
            direct_calls(pe,original,0x1d9b350)==selected|{0x1d9e05c},"Exact 70 application Get inventory required")
    require(direct_calls(after,target,0x1d9b350)=={0x1d9e05c},"Application Get coverage incomplete; only engine WWW may remain original")
    require(pe.get_data(0x6184a6,5)==after.get_data(0x6184a6,5),"Central original Send changed")
    oldimports=[(r.dll,[(i.name,i.address-pe.OPTIONAL_HEADER.ImageBase)for i in r.imports])for r in pe.DIRECTORY_ENTRY_IMPORT]
    imports=[(r.dll,[(i.name,i.address-after.OPTIONAL_HEADER.ImageBase)for i in r.imports])for r in after.DIRECTORY_ENTRY_IMPORT]
    require(imports[:len(oldimports)]==oldimports,"Original imports changed")
    require([x[0]for x in imports[len(oldimports):]]==[b"NebulaNetworkBridge.dll",b"NebulaPublicAccess.dll"],"Unexpected helper imports")
    require(imports[-2][1][0][0]==b"NebulaAutomation_JoinQueueReady" and len(imports[-2][1])==1,"Direct networking gate dependency differs")
    oldrows=[(r.struct.BeginAddress,r.struct.EndAddress,r.struct.UnwindData)for r in pe.DIRECTORY_ENTRY_EXCEPTION]
    rows=[(r.struct.BeginAddress,r.struct.EndAddress,r.struct.UnwindData)for r in after.DIRECTORY_ENTRY_EXCEPTION]
    rowset=set(rows)
    require(all(r in rowset for r in oldrows),"Original unwind rows changed")
    require(not any(s.Characteristics&0xa0000000==0xa0000000 for s in after.sections),"RWX sections forbidden")
    require(after.get_data(0x5e5010,0x4b0)==pe.get_data(0x5e5010,0x4b0),"Original queue drain body changed")
    pe.close();after.close()
    return dict(original_text_changes_allowlisted=len(changes),original_executable_sections=executable_sections,
                approved_network_ranges=len(ranges),omitted_sites_preserved=preserved,
                original_import_rows_preserved=len(oldimports),original_unwind_rows_preserved=len(oldrows),
                application_get_sites=70,unmodified_engine_www_get="0x1d9e05c",central_send_unchanged=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--originals",type=Path,required=True)
    p.add_argument("--build",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    require(not a.output.exists(),"Fresh verification receipt required")
    contract=json.loads((HERE/"network-profile-contract.json").read_text())
    receipt=json.loads((a.build/"build-receipt.LOCAL-DO-NOT-COMMIT.json").read_text())
    result=verify(read(a.originals/"GameAssembly.dll",ORIGINALS["GameAssembly.dll"]),(a.build/"GameAssembly.dll").read_bytes(),receipt,contract)
    for path,pin in ORIGINALS.items():read(a.originals/path,pin)
    remote=receipt.get("transport")=="remote"
    for name,pin in (("NebulaNetworkBridge.dll",contract["bridge_sha256"]),("NebulaRegistryBridge.dll",REGISTRY),("NebulaPublicAccess.dll",REMOTE_PUBLIC if remote else PUBLIC)):
        read(a.build/name,pin)
    plan=json.loads((a.build/"release-input-network-only.PROVISIONAL.json").read_text())
    expected={"GameAssembly.dll","Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat","NebulaNetworkBridge.dll",
              "NebulaRegistryBridge.dll","NebulaPublicAccess.dll","steam_appid.txt"}
    if remote:expected.add("NebulaRemoteTransport.exe");read(a.build/"NebulaRemoteTransport.exe",REMOTE_TRANSPORT)
    require(plan.get("profile")=="network-only" and {x["path"]for x in plan["artifacts"]}==expected and len(plan["artifacts"])==len(expected),
            "Strict six/seven-artifact release-input plan required")
    require(not (a.build/"globalgamemanagers").exists() and not (a.build/"charactereditor").exists(),"Input/editor targets must not be produced")
    result.update(format="network-only-client-static-verification-v1",passed=True,input_assets_original=True,
                  exact_profile_artifact_count=len(expected),native_runtime_accepted=False,installed=False)
    a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps({"passed":True,"preserved_sites":len(OMITTED_SITES)}))

if __name__=="__main__":main()
