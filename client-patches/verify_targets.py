"""Offline verification of reconstructed profile outputs; executes test fixtures only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import pefile

HERE=Path(__file__).resolve().parent
SHA=lambda b:hashlib.sha256(b).hexdigest()
TUPLES={
    "default":("d59155564b142aa24dcfab03a47290d43261dccbfd55ea3a06543fffe65fda04","c880fb8df3265da1432ff3e6683156e2941abf972ad23df8e15699f38fea6e19"),
    "free-mouse":("39ad8c096357f4a1e56b90524175f67b8e6cc88dcedf2c3bc0fbf87178271e3b","68415abf23ee90cbc3e9c6294097c0387eea8b29ddae42eb1fbc290739573083"),
}

def check(ok,reason):
    if not ok:raise ValueError(reason)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets",type=Path,required=True)
    parser.add_argument("--originals",type=Path,required=True)
    parser.add_argument("--cxx",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    a=parser.parse_args()
    check(not a.output.exists(),"Fresh verification output required")
    lock_path=HERE/"source-lock.json"
    lock=json.loads(lock_path.read_bytes())
    check(SHA(lock_path.read_bytes())=="4399d7a031de47a1870feddd7c6299c6a56a4e7a73d047ec1a2867a794b9bf62","Source lock differs")
    for name,pin in lock["files"].items():
        check(SHA((HERE/name).read_bytes())==pin,"Source closure differs: "+name)
    baseline=lock["helper_baseline"]
    checks=[]
    for name,(ga_pin,helper_pin) in TUPLES.items():
        folder=a.targets/name
        check(SHA((folder/"GameAssembly.dll").read_bytes())==ga_pin,"GameAssembly tuple differs: "+name)
        check(SHA((folder/"NebulaAutomation.dll").read_bytes())==helper_pin,"Helper tuple differs: "+name)
        for relative,pin in baseline["source"].items():
            raw=(folder/"helper-source"/relative).read_bytes()
            if relative=="movement_profile.h":
                expected=(HERE/"native-automation"/relative).read_bytes().replace(TUPLES["free-mouse"][0].encode(),ga_pin.encode())
                check(raw==expected,"Only exact GA header binding may change")
            else:check(SHA(raw)==pin,"Network or other helper source differs: "+relative)
        checks.append(name+" exact GA/helper tuple and full helper source closure")
    settings=(a.targets/"default/helper-source/settings_native_core.inc").read_text()
    constants=re.search(r'(constexpr const char \*kCursorSafeNormalGameAssemblySha256=.*?;\s*constexpr const char \*kCursorSafeCohortGameAssemblySha256=.*?;)',settings,re.S).group(1)
    predicate=re.search(r'(bool cursor_safe_profile\(\) \{.*?\n\})',settings,re.S).group(1)
    with tempfile.TemporaryDirectory(prefix="nebula-cursor-profile-check-") as temporary:
        out=Path(temporary)
        for name,pin,wanted in (
            ("default",TUPLES["default"][0],False),
            ("free-mouse",TUPLES["free-mouse"][0],True),
            ("cohort","40ce54b0b003b5d22be142787413111e105c4e26c8c25bde758c604f20b457eb",True),
            ("unknown","0"*64,False),
        ):
            src=out/(name+".cpp");exe=out/(name+".exe")
            src.write_text('#include <cstring>\n#define NEBULA_MOVEMENT_GAMEASSEMBLY_SHA256 "'+pin+'"\n'+constants+'\n'+predicate+'\nint main(){return cursor_safe_profile()=='+str(wanted).lower()+'?0:29;}\n',encoding="utf-8")
            subprocess.run([str(a.cxx),"-std=c++17","-Wall","-Wextra","-Werror",str(src),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
            checks.append("actual settings cursor safe-list predicate "+name)
    original=(a.originals/"GameAssembly.dll").read_bytes()
    check(SHA(original)=="c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac","Pristine original differs")
    pristine=pefile.PE(data=original)
    target=pefile.PE(str(a.targets/"default/GameAssembly.dll"))
    for rva,end in ((0x6a93e0,0x6a93fb),(0x1b6b7d0,0x1b6b801),(0x1b6b810,0x1b6b843)):
        check(pristine.get_data(rva,end-rva)==target.get_data(rva,end-rva),"Default original cursor method changed")
        checks.append("default exact pristine cursor body "+hex(rva))
    for profile in TUPLES:
        plan=json.loads((a.targets/("release-input-"+profile+".json")).read_bytes())
        check(plan["status"]=="provisional" and len(plan["artifacts"])==8,"Release input shape/status differs")
        for artifact in plan["artifacts"]:
            if "target" in artifact:
                check(SHA(Path(artifact["target"]).read_bytes())==artifact["target_sha256"],"Release target differs")
        metadata=[x for x in plan["artifacts"] if x["path"].endswith("global-metadata.dat")]
        check(len(metadata)==1 and "target" not in metadata[0],"Metadata must be parameterized by the Rust patcher")
        checks.append(profile+" exact eight-artifact provisional bundle input")
    result=dict(format="nebula-portable-source-target-offline-verification-v1",passed=True,checks=checks,
        source_files_verified=len(lock["files"]),actual_predicate_cases=4,original_cursor_methods_compared=3,
        installed=False,game_launched=False,native_runtime_accepted=False)
    a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"checks":len(checks),"receipt_sha256":SHA(a.output.read_bytes())}))

if __name__=="__main__":main()
