"""Build reviewed preservation deltas. Writes only a new output directory.

This is artifact construction/static verification, not a game or server test.
Python standard library only; the compiled Rust --patcher is the UnityFS decoder.
Every target requires its independently reviewed hash in the input plan.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

BASE = {
    "GameAssembly.dll": "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac",
    "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat": "c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1",
    "Nebula Realms_Data/globalgamemanagers": "ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466",
    "Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor": "5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0",
}
HELPERS = {"NebulaRegistryBridge.dll", "NebulaAutomation.dll", "NebulaPublicAccess.dll", "steam_appid.txt"}
NETWORK_CORE = set(list(BASE)[:2])
NETWORK_HELPERS = {"NebulaRegistryBridge.dll", "NebulaNetworkBridge.dll", "NebulaPublicAccess.dll", "steam_appid.txt"}
OPTIONAL = {"NebulaRemoteTransport.exe"}
EXE = "77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d"
def sha(b): return hashlib.sha256(b).hexdigest()
def require(condition, message):
    if not condition: raise ValueError(message)
def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))

def profile_paths(plan):
    profile = plan.get("profile")
    require("profile" not in plan or profile == "network-only", "Unknown client profile")
    required = NETWORK_CORE | NETWORK_HELPERS if profile == "network-only" else set(BASE) | HELPERS
    paths = [a["path"] for a in plan.get("artifacts", [])]
    require(len(paths) == len(set(paths)) and required.issubset(paths) and set(paths).issubset(required | OPTIONAL),
            "Profile requires its exact core/helper set, optionally remote transport; mixed or omitted artifacts are rejected")
    if "transport" in plan:
        require(profile == "network-only" and plan["transport"] == ("remote" if "NebulaRemoteTransport.exe" in paths else "direct"),
                "Release-input transport must match the derived network-only artifact set")
    return profile
def checked(path, pin):
    require(isinstance(pin, str) and len(pin) == 64, "Every source/target needs an explicit reviewed SHA256")
    data = Path(path).read_bytes()
    require(len(data) <= 256*1024*1024 and sha(data) == pin, f"Pin mismatch: {path}")
    return data

def encode_delta(source, target):
    """Exact source-reference matching; no compression of a complete target file."""
    anchors = {}
    zero = bytes(64)
    for i in range(0, max(0, len(source)-24+1), 32):
        key = source[i:i+24]
        if not any(key): continue
        positions = anchors.setdefault(key, [])
        if len(positions) < 4: positions.append(i)
    ops = []; pending = bytearray(); p = 0; literals = 0; copied = 0; zeros = 0
    def flush():
        nonlocal literals
        if pending:
            ops.append(b"\1" + struct.pack("<Q", len(pending)) + pending)
            literals += len(pending); pending.clear()
    while p < len(target):
        if target[p:p+64] == zero:
            end = p+64
            while end+65536 <= len(target) and target[end:end+65536] == bytes(65536): end += 65536
            while end < len(target) and target[end] == 0: end += 1
            flush(); ops.append(b"\2"+struct.pack("<Q",end-p)); zeros += end-p; p=end; continue
        best_at = best = 0
        for at in anchors.get(target[p:p+24], ()):
            count = 24; bound = min(len(source)-at, len(target)-p)
            for stride in (65536,1024,32,1):
                while count+stride <= bound and source[at+count:at+count+stride] == target[p+count:p+count+stride]: count += stride
            if count > best: best_at,best = at,count
        if best >= 32:
            flush();ops.append(b"\0"+struct.pack("<QQ",best_at,best));copied += best;p += best
        else:
            pending.append(target[p]);p += 1
            if len(pending) == 65536: flush()
    flush()
    require(literals <= min(2*1024*1024,max(128,len(target)//4)), "Delta literal budget exceeded: refusing possible full proprietary target redistribution; improve source view")
    payload = b"NBD1"+struct.pack("<IQ",len(ops),len(target))+b"".join(ops)
    # Independent decoder validates construction before emitting a release payload.
    result = bytearray(); offset=16
    for _ in ops:
        kind=payload[offset];offset+=1
        if kind == 0:
            at,n=struct.unpack_from("<QQ",payload,offset);offset+=16;result.extend(source[at:at+n])
        else:
            n,=struct.unpack_from("<Q",payload,offset);offset+=8
            if kind == 1: result.extend(payload[offset:offset+n]);offset+=n
            else: result.extend(bytes(n))
    require(offset == len(payload) and result == target, "Constructed delta failed exact static reconstruction")
    return payload, {"copied_bytes":copied,"authored_literal_bytes":literals,"zero_bytes":zeros,"operations":len(ops),"sha256":sha(payload)}

def canonical(patcher, data_path, output):
    process = subprocess.run([str(patcher),"bundle-view","--input",str(data_path),"--output",str(output)],capture_output=True,text=True)
    require(process.returncode == 0, "Rust UnityFS canonicalizer rejected source: "+process.stderr)
    data=output.read_bytes();require(process.stdout.strip()==sha(data),"Canonicalizer output hash mismatch")
    # Independent shipped-asset reader: compare exact decoded node bytes from
    # original compressed input against our uncompressed view, not a save/repack.
    expected=unitypy_nodes(data_path)
    actual=[{k:n[k] for k in ("name","size","flags","sha256")}for n in nodes(data)]
    require(actual==expected,"Independent UnityPy decoded-node parity mismatch")
    return data

def unitypy_nodes(path):
    import UnityPy
    environment=UnityPy.load(str(path));bundle=environment.file
    result=[]
    for name,file in bundle.files.items():
        reader=getattr(file,"reader",file);content=bytes(reader.bytes)
        result.append({"name":name,"size":len(content),"flags":file.flags,"sha256":sha(content)})
    return result

def nodes(data):
    """Independently inspect only deterministic uncompressed canonical view."""
    p=8
    version,=struct.unpack_from(">I",data,p);p+=4
    for _ in range(2): p=data.index(0,p)+1
    size,compressed,expanded,flags=struct.unpack_from(">QIII",data,p);p+=20
    require(size==len(data) and flags==0x40 and compressed==expanded,"Noncanonical UnityFS view")
    if version>=7: p=(p+15)&~15
    info=data[p:p+expanded];body=data[p+expanded:];n,=struct.unpack_from(">I",info,16)
    require(n==1,"Canonical view must have one block")
    a,b,mode=struct.unpack_from(">IIH",info,20);require(a==b==len(body) and mode==0,"Bad canonical block")
    count,=struct.unpack_from(">I",info,30);q=34;result=[]
    for _ in range(count):
        off,length,flags=struct.unpack_from(">QQI",info,q);q+=20;end=info.index(0,q);name=info[q:end].decode("utf-8");q=end+1
        require(off+length<=len(body),"Canonical node exceeds body")
        result.append({"name":name,"offset":off,"size":length,"flags":flags,"sha256":sha(body[off:off+length])})
    require(q==len(info),"Canonical node table trailing data")
    return result

def build(args):
    plan=load(args.plan);out=Path(args.output).resolve()
    require(not out.exists(),"Output must not exist; build never overwrites a previous bundle")
    require(plan.get("format")=="nebula-release-input-v1" and plan.get("app_id")=="919290" and plan.get("build_id")=="11018722","Unsupported input plan")
    status=plan.get("status");require(status in ("provisional","frozen"),"Missing status")
    require(plan.get("review") and not (status=="frozen" and plan["review"].startswith("PENDING")),"Missing final review")
    artifacts=plan.get("artifacts",[]);paths=[a["path"] for a in artifacts]
    profile=profile_paths(plan)
    # Freeze proof inputs are independently pinned and included as review evidence, never run.
    proofs=plan.get("review_evidence",[])
    proof_roles={"native-composition","https-69-get-hooks","helper-composition"}
    if profile != "network-only": proof_roles.add("unityfs-runtime-acceptance")
    require(status!="frozen" or {x.get("role") for x in proofs}>=proof_roles,"Frozen public release needs exact composition/helper acceptance evidence and UnityFS runtime evidence when the editor is patched")
    originals=Path(plan["originals"])
    checked(originals/"Nebula Realms.exe",EXE)
    preflight={}
    for a in artifacts:
        path=a["path"]
        if path in BASE: checked(originals/path,BASE[path])
        if path.endswith("global-metadata.dat"): continue
        require(path!="steam_appid.txt" or a.get("target_sha256")==sha(b"919290"),"steam_appid.txt must contain only 919290")
        preflight[path]=checked(a["target"],a.get("target_sha256"))
        if path=="steam_appid.txt":require(preflight[path]==b"919290","Unexpected Steam app-id content")
    evidence=[]
    for item in proofs:
        content=checked(item["path"],item["sha256"]);require(len(content)<=4*1024*1024,"Review evidence too large")
        evidence.append((item,content))
    out.mkdir(parents=True);(out/"payloads").mkdir();(out/"evidence").mkdir();scratch=out/"build-only-do-not-distribute";scratch.mkdir()
    manifest={"format":"nebula-patch-v1","app_id":"919290","build_id":"11018722","status":status,"review":plan["review"],"artifacts":[]}
    if profile is not None: manifest["profile"]=profile
    provenance={"format":"nebula-bundle-construction-v1","input_plan_sha256":sha(Path(args.plan).read_bytes()),"copyright_policy":"Only source-referenced deltas and project-owned helper files are distributable. build-only-do-not-distribute must be excluded.","artifacts":[],"review_evidence":[]}
    try:
        for i,a in enumerate(artifacts):
            path=a["path"];base=BASE.get(path);entry={"path":path,"operation":"owned_file","original_sha256":base,"accepted_existing":a.get("accepted_existing",[]),"payload":None,"payload_sha256":None,"payload_size":None,"source_view_sha256":None,"output_sha256":None}
            record={"path":path,"original_sha256":base,"reviewed_target_sha256":a.get("target_sha256")}
            if path.endswith("global-metadata.dat"):
                entry["operation"]="metadata";record["recipe"]="Rust endpoint::patch: original pinned metadata v29 literal tables; exact4 literal classes only"
            else:
                target=preflight[path]
                if base:
                    source=(originals/path).read_bytes();entry["operation"]="delta"
                    if path.endswith("charactereditor"):
                        entry["operation"]="unityfs_delta"
                        source=canonical(Path(args.patcher),originals/path,scratch/f"{i}-original.unityfs")
                        target=canonical(Path(args.patcher),Path(a["target"]),scratch/f"{i}-target.unityfs")
                        record["source_nodes"]=nodes(source);record["target_nodes"]=nodes(target)
                        require([x["name"] for x in record["source_nodes"]]==[x["name"] for x in record["target_nodes"]],"UnityFS node set changed; needs a new explicit recipe")
                        record["canonical_layout_differs_from_manual"]=True
                    entry["source_view_sha256"]=sha(source)
                    payload,statistics=encode_delta(source,target);record["delta"]=statistics
                else: payload=target;record["project_owned"]=True
                relative=f"payloads/{i:02d}.{'nbd' if base else 'bin'}";(out/relative).write_bytes(payload)
                entry.update(payload=relative,payload_sha256=sha(payload),payload_size=len(payload),output_sha256=sha(target))
            manifest["artifacts"].append(entry);provenance["artifacts"].append(record)
        for i,(item,content) in enumerate(evidence):
            relative=f"evidence/{i:02d}.json";(out/relative).write_bytes(content);provenance["review_evidence"].append({"role":item["role"],"path":relative,"sha256":sha(content)})
        manifest_bytes=(json.dumps(manifest,indent=2)+"\n").encode();(out/"manifest.json").write_bytes(manifest_bytes)
        (out/"manifest.sha256").write_text(sha(manifest_bytes)+"\n",encoding="ascii")
        (out/"construction-receipt.json").write_text(json.dumps(provenance,indent=2)+"\n",encoding="utf-8")
        # Scratch holds complete decoded proprietary files; remove only the known files we created.
        for child in scratch.iterdir(): require(child.is_file() and not child.is_symlink(),"Unexpected scratch entry");child.unlink()
        scratch.rmdir()
        print(json.dumps({"manifest_sha256":sha(manifest_bytes),"status":status,"artifacts":len(artifacts),"output":str(out)}))
    except Exception:
        print("BUILD INCOMPLETE: do not distribute this output; inspect build-only-do-not-distribute for proprietary scratch files.")
        raise

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",required=True);parser.add_argument("--patcher",required=True);parser.add_argument("--output",required=True)
    build(parser.parse_args())
