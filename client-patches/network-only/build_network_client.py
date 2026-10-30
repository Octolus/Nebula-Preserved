"""Build a provisional networking-only client profile from locally owned originals.

New private output only. No installation, DLL loading, game launch, server or
publishing. The original controller/input assets and rendering code are kept.
The separately retained optional/test pipeline is not consumed by this build.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import pefile

HERE = Path(__file__).resolve().parent
LOCK = "b657ab12a863baacb0ac4380532250a0ee5cd1e379f85ef7ada78312ccc43898"
ORIGINALS = {
    "GameAssembly.dll": "c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac",
    "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat": "c59807c2950c1051202ae7d96744d126be4c489c7719f7e2d8d207f8f75681c1",
    "Nebula Realms_Data/globalgamemanagers": "ecdebe7c899776956a4d5fb801f37f04128ec9bef72e744cd1e7fd5349ce8466",
    "Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor": "5d1713e79b4e5bab090a3d57eb4d4c4139999629bb4a2038412a6cb92d1b02e0",
    "Nebula Realms.exe": "77bdecc37804194305c2402be5ac0851570f395bf9af3fb4ee03030c6d779d0d",
}
REGISTRY = "e493d6fa9af94df6626e950ee8e4483ede10d94fc81405b394090dd0e047ef10"
PUBLIC = "d0a37cfd1e47e9ec706d92c8b29dd9b29a4cfc9ca5c9891b0f427ba2510a93aa"
REMOTE_PUBLIC = "909284bf0e351ed037ea3acc22cd06ff57d2a17c3bfb83cd02df48b4e066948f"
REMOTE_TRANSPORT = "e5baacfc3f9ad884610bf0c32c71d9e533f8df05d69264b4aedb97041c18bde5"
sha = lambda b: hashlib.sha256(b).hexdigest()

def require(ok, why):
    if not ok:
        raise ValueError(why)

def read(path, pin):
    data = Path(path).read_bytes(); require(sha(data) == pin, "Pinned input differs: " + str(path)); return data

def load(name):
    spec = importlib.util.spec_from_file_location("network_client_"+Path(name).stem,HERE/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def adapted_input(module, key, prior_pin, new_pin, current):
    # Recipe bytes and all native-site/ABI checks remain unchanged. Only the
    # accepted intermediate hash changes because optional stages are omitted.
    require(getattr(module,key) == prior_pin and sha(current) == new_pin, "Reviewed recipe input adaptation differs")
    setattr(module,key,new_pin)

def compile_bridge(cxx, out, ga_pin, contract):
    source = out / "private-network-bridge-source"; source.mkdir()
    for name in ("join_queue_gate.cpp","join_queue_gate.h","movement_profile.h"):
        shutil.copyfile(HERE/"native-automation"/name,source/name)
    header = source/"movement_profile.h"; data = header.read_bytes()
    old = b"39ad8c096357f4a1e56b90524175f67b8e6cc88dcedf2c3bc0fbf87178271e3b"
    require(data.count(old) == 1, "Gate profile source differs")
    header.write_bytes(data.replace(old,ga_pin.encode()))
    dll = out/"NebulaNetworkBridge.dll"
    subprocess.run([str(cxx),"-std=c++20","-O2","-Wall","-Wextra","-Werror","-fno-exceptions","-fno-rtti",
                    "-shared","-static","-static-libgcc","-static-libstdc++",
                    "-Wl,--no-insert-timestamp,--image-base,0x180000000,--strip-all","-I",str(source),"-o",str(dll),
                    str(source/"join_queue_gate.cpp"),"-lbcrypt"],check=True)
    data = read(dll,contract["bridge_sha256"]); pe = pefile.PE(data=data)
    require(sorted(r.dll.decode() for r in pe.DIRECTORY_ENTRY_IMPORT) == contract["bridge_imports"], "Bridge dependencies differ")
    require(sorted(r.name.decode() for r in pe.DIRECTORY_ENTRY_EXPORT.symbols if r.name) ==
            ["NebulaAutomation_JoinQueueReady"], "Only unchanged networking gate may be exported")
    require(not pe.OPTIONAL_HEADER.DATA_DIRECTORY[13].Size and
            all(not r.forwarder for r in pe.DIRECTORY_ENTRY_EXPORT.symbols), "Unexpected delayed/forwarded dependency")
    pe.close(); return dll

def release_plan(out, originals, contract, remote=False, public_access=None, transport=None):
    """Compose only exact pinned artifacts; never launch or configure transport."""
    read(out/"GameAssembly.dll",contract["ga_sha256"])
    public_access = Path(public_access) if public_access else out/"NebulaPublicAccess.dll"
    read(public_access,REMOTE_PUBLIC if remote else PUBLIC)
    if remote:
        require(transport is not None,"Remote profile needs its exact matching sidecar")
        read(transport,REMOTE_TRANSPORT)
    artifacts = [dict(path="GameAssembly.dll",target=str((out/"GameAssembly.dll").resolve()),target_sha256=contract["ga_sha256"],accepted_existing=[contract["ga_sha256"]]),
                 dict(path="Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat",accepted_existing=["69cf396cfb86d1e22ae110c032b7fa707250b6aec3978f42d0b5197f9956248b"])]
    for name,pin in (("NebulaNetworkBridge.dll",contract["bridge_sha256"]),("NebulaRegistryBridge.dll",REGISTRY),("steam_appid.txt",sha(b"919290"))):
        read(out/name,pin)
        artifacts.append(dict(path=name,target=str((out/name).resolve()),target_sha256=pin,accepted_existing=[pin]))
    artifacts.append(dict(path="NebulaPublicAccess.dll",target=str(public_access.resolve()),target_sha256=REMOTE_PUBLIC if remote else PUBLIC,
                          accepted_existing=[REMOTE_PUBLIC if remote else PUBLIC]))
    if remote:
        artifacts.append(dict(path="NebulaRemoteTransport.exe",target=str(Path(transport).resolve()),target_sha256=REMOTE_TRANSPORT,accepted_existing=[REMOTE_TRANSPORT]))
    return dict(format="nebula-release-input-v1",profile="network-only",transport="remote" if remote else "direct",
                app_id="919290",build_id="11018722",status="provisional",
                review="Development networking-only source. Direct local forwarding only; public HTTPS requires remote sidecar mode. Native acceptance pending.",
                originals=str(originals),review_evidence=[],artifacts=artifacts)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--originals",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--cc",type=Path,required=True);p.add_argument("--cxx",type=Path,required=True)
    p.add_argument("--registry-bridge",type=Path,required=True,help="Unchanged independently reviewed registry DLL")
    p.add_argument("--public-access",type=Path,required=True,help="Reviewed loopback-consumer PublicAccess DLL")
    p.add_argument("--transport",choices=("direct","remote"),default="direct")
    p.add_argument("--remote-transport",type=Path,help="Exact matching TLS sidecar; required only for remote profile")
    a = p.parse_args(); originals = a.originals.resolve(strict=True); out = a.output.resolve()
    require(not out.exists() and not out.is_relative_to(originals) and not out.is_relative_to(HERE) and
            "steamapps" not in [x.lower() for x in out.parts], "Fresh isolated output outside sources/Steam required")
    lock = json.loads(read(HERE/"source-lock.json",LOCK))
    for name,pin in lock["files"].items(): read(HERE/name,pin)
    contract = json.loads((HERE/"network-profile-contract.json").read_text())
    for name,pin in ORIGINALS.items(): read(originals/name,pin)
    remote = a.transport == "remote"
    require(remote == (a.remote_transport is not None),"Sidecar is required only for explicit remote profile")
    bridge = read(a.registry_bridge,REGISTRY); public = read(a.public_access,REMOTE_PUBLIC if remote else PUBLIC)
    if remote: read(a.remote_transport,REMOTE_TRANSPORT)
    out.mkdir(parents=True); scratch = out/"private-build-scratch-DO-NOT-DISTRIBUTE";scratch.mkdir()
    current = (originals/"GameAssembly.dll").read_bytes(); stages = []
    def obj(name,pin):
        target = scratch/(Path(name).stem+".o")
        subprocess.run([str(a.cc),"-c",str(HERE/name),"-o",str(target)],check=True)
        return read(target,pin)
    def stage(name,data,report=None):
        nonlocal current
        expected = contract["stages"][len(stages)]
        require(expected == {"name":name,"source_sha256":sha(current),"output_sha256":sha(data)}, "Exact network stage differs")
        stages.append({**expected,"report":report});current = data
    wardrobe = load("recipes/make_client_copy.py"); data = bytearray(current)
    require(data[wardrobe.OFFSET:wardrobe.OFFSET+2] == wardrobe.BEFORE,"Wardrobe consumer branch differs")
    data[wardrobe.OFFSET:wardrobe.OFFSET+2] = wardrobe.AFTER; stage("wardrobe-consumer",bytes(data))
    data,report = load("recipes/rapid_boat_patch.py").build(current,obj("shims/rapid_boat_exit.s","24fc28d939cb1dda6c74662ecd53a22d2d3923d6573a6adddf194fbe19a83608"))
    stage("rapid-exit-network-report",data,report)
    registry = load("recipes/interaction_registry_patch.py")
    adapted_input(registry,"SOURCE_SHA","ec6f909d3af35c89cd287a2803b86839cd5d1b168bc1f76517eed2494c85e01b",
                  contract["stages"][2]["source_sha256"],current)
    data,report = registry.build(current,obj("shims/interaction_registry_bridge.s",registry.OBJECT_SHA),bridge)
    stage("registry-save-snapshot",data,report)
    settings = load("recipes/settings_preservation_patch.py")
    adapted_input(settings,"SOURCE_SHA256","af25cec2ba6a9496f7c34b5ea8224f4ef5ab9f596bda6ae35bcb44197f30b195",
                  contract["stages"][3]["source_sha256"],current)
    data,report = settings.build(current); stage("network-settings-save-hydration",data,report)
    data,report = load("pe-composition/network_hooks.py").compose(current,
        obj("pe-composition/network_hooks.s",contract["wrapper_object_sha256"]),
        contract["stages"][4]["source_sha256"],contract["wrapper_object_sha256"])
    stage("https70-direct-join-gate",data,report)
    require(sha(current) == contract["ga_sha256"], "Final networking profile differs")
    (out/"GameAssembly.dll").write_bytes(current); compile_bridge(a.cxx,out,sha(current),contract)
    (out/"NebulaRegistryBridge.dll").write_bytes(bridge);(out/"NebulaPublicAccess.dll").write_bytes(public)
    (out/"steam_appid.txt").write_bytes(b"919290")
    if remote: shutil.copyfile(a.remote_transport,out/"NebulaRemoteTransport.exe")
    plan = release_plan(out,originals,contract,remote,transport=out/"NebulaRemoteTransport.exe" if remote else None)
    (out/"release-input-network-only.PROVISIONAL.json").write_text(json.dumps(plan,indent=2)+"\n",encoding="utf-8")
    for name,pin in ORIGINALS.items(): read(originals/name,pin)
    receipt = dict(format="network-only-client-build-v2",source_lock_sha256=LOCK,stages=stages,ga_sha256=sha(current),
                   bridge_sha256=contract["bridge_sha256"],original_assets_unchanged=True,installed=False,game_launched=False,
                   transport=a.transport,native_runtime_accepted=False,public_bundle_compatible=False)
    (out/"build-receipt.LOCAL-DO-NOT-COMMIT.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"ga_sha256":sha(current),"network_bridge_sha256":contract["bridge_sha256"],"provisional":True}))

if __name__ == "__main__": main()
