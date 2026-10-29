"""Offline source-backed networking profile checks. Never loads a game DLL."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import build_network_client as build
import verify_network_client as scope

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("originals","build","legacy-default","prior-network-ga","legacy-public-access","remote-public-access","remote-transport","cc","cxx","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    build.require(not out.exists() and not out.is_relative_to(HERE) and
                  "steamapps" not in [v.lower()for v in out.parts],"Fresh isolated offline output required")
    out.mkdir(parents=True)
    contract=json.loads((HERE/"network-profile-contract.json").read_text())
    receipt=json.loads((a.build/"build-receipt.LOCAL-DO-NOT-COMMIT.json").read_text())
    original=build.read(a.originals/"GameAssembly.dll",build.ORIGINALS["GameAssembly.dll"])
    target=build.read(a.build/"GameAssembly.dll",contract["ga_sha256"])
    current=scope.verify(original,target,receipt,contract)
    # Replace only this test's expected target digest so it reaches the scope
    # predicate. Production source/profile pins are never widened.
    old=build.read(a.legacy_default,"d59155564b142aa24dcfab03a47290d43261dccbfd55ea3a06543fffe65fda04")
    try:scope.verify(original,old,receipt,{**contract,"ga_sha256":build.sha(old)})
    except ValueError as error:
        build.require(str(error)=="Non-network change in original executable text","Old profile failed for an unexpected reason")
    else:raise AssertionError("Keyboard-enabled prior default must fail networking-only scope")
    prior=build.read(a.prior_network_ga,"4557a8b60b2c41376ffbcb61e4fe637639c738a964cc369829c09c5f21dd1373")
    try:scope.verify(original,prior,receipt,{**contract,"ga_sha256":build.sha(prior)})
    except ValueError as error:
        build.require(str(error)=="Application Get coverage incomplete; only engine WWW may remain original","Prior 69-site profile failed for an unexpected reason")
    else:raise AssertionError("Prior 69-site profile must fail live central request coverage")
    remote=build.release_plan(a.build,a.originals,contract,True,a.remote_public_access,a.remote_transport)
    build.require(remote["profile"]=="network-only" and len(remote["artifacts"])==7,"Exact remote profile differs")
    try:build.release_plan(a.build,a.originals,contract,True,a.legacy_public_access,a.remote_transport)
    except ValueError as error:
        build.require(str(error).startswith("Pinned input differs"),"Unexpected mismatched-pair rejection")
    else:raise AssertionError("Historical direct wrapper must not accept fresh TLS sidecar")
    obj=out/"network_hooks.o"
    subprocess.run([str(a.cc),"-c",str(HERE/"pe-composition/network_hooks.s"),"-o",str(obj)],check=True)
    build.read(obj,contract["wrapper_object_sha256"])
    common=[str(a.cxx),"-std=c++20","-O2","-Wall","-Wextra","-Werror"]
    shim=out/"test_network_shim.exe"
    subprocess.run(common+[str(HERE/"test_network_shim.cpp"),str(obj),"-o",str(shim)],check=True)
    subprocess.run([str(shim)],check=True)
    gate=out/"test_join_queue_gate.exe"
    subprocess.run(common+[str(HERE/"native-automation/test_join_queue_gate.cpp"),"-o",str(gate)],check=True)
    result=subprocess.run([str(gate)],check=True,capture_output=True,text=True)
    build.require("TOTAL 30 checks passed" in result.stdout,"Actual gate collector/policy completion differs")
    checks=dict(format="network-only-source-checks-v2",passed=True,actual_direct_iat_shim_cases=6,
                actual_windows_unwind=True,actual_gate_collector_checks=30,old_keyboard_profile_rejected=True,
                prior_69_site_profile_rejected_at_actual_central_coverage=True,
                matching_remote_plan_artifacts=7,mismatched_wrapper_sidecar_rejected=True,scope=current,
                native_runtime_accepted=False,installed=False,game_launched=False)
    (out/"checks.PRIVATE.json").write_text(json.dumps(checks,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"gate_collector_checks":30,"new_shim_cases":6,"remote_artifacts":7}))

if __name__=="__main__":main()
