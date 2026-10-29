"""Build reviewed authored helpers into a new external directory; never installs or launches."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pefile
import build_client_targets as stage

HERE=Path(__file__).resolve().parent
SHA=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def main(a):
    compiler=a.cxx.resolve(strict=True)
    out=a.output.resolve()
    if out.exists() or out.is_relative_to(HERE) or "steamapps" in [x.lower() for x in out.parts]:
        raise ValueError("Output must be a new external directory outside sources and Steam")
    lock=json.loads(stage.read(HERE/"source-lock.json",stage.LOCK))
    for name,pin in lock["files"].items():stage.read(HERE/name,pin)
    out.mkdir(parents=True)
    if a.component=="automation":
        ga=stage.DEFAULT_JOIN if a.profile=="default" else stage.FREE_JOIN
        dll=stage.helper(SimpleNamespace(cxx=compiler),lock["helper_baseline"],out,ga)
        source={name:SHA(out/"helper-source"/name) for name in lock["helper_baseline"]["source"]}
    else:
        ga=None
        dll=out/"NebulaRegistryBridge.dll"
        source_file=HERE/"native-registry/interaction_registry_bridge.cpp"
        # Preserve the independently reviewed registry build flags exactly.
        command=[str(compiler),"-std=c++17","-O2","-Wall","-Wextra","-Werror","-shared","-static",
            "-Wl,--no-insert-timestamp","-Wl,--image-base,0x180000000","-o",str(dll),str(source_file)]
        subprocess.run(command,check=True)
        stage.read(dll,stage.BRIDGE)
        source={source_file.name:SHA(source_file)}
    pe=pefile.PE(str(dll))
    imports=sorted(row.dll.decode() for row in pe.DIRECTORY_ENTRY_IMPORT)
    exports=sorted(row.name.decode() for row in pe.DIRECTORY_ENTRY_EXPORT.symbols if row.name)
    if any(not (name.lower().startswith("api-ms-win-") or name.lower() in ("kernel32.dll","bcrypt.dll")) for name in imports):
        raise ValueError("Unexpected helper dependency")
    report=dict(component=a.component,profile=a.profile if a.component=="automation" else None,
        ga_profile_sha256=ga,source_sha256=source,compiler_sha256=SHA(compiler),output_sha256=SHA(dll),
        imports=imports,exports=exports,installed=False,target_executed=False,production_ready=False,
        settings_cursor_safe_profile=a.component=="automation" and a.profile=="free-mouse")
    (out/"build-receipt.LOCAL-DO-NOT-COMMIT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"component":a.component,"profile":report["profile"],"output_sha256":report["output_sha256"]}))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component",choices=("automation","registry"),required=True)
    parser.add_argument("--profile",choices=("default","free-mouse"),default="default",help="Automation profile; default preserves original cursor behavior")
    parser.add_argument("--cxx",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    main(parser.parse_args())
