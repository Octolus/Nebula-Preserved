"""Isolated artifact construction: decoded CharacterEditor delta, never installs.

The two complete decoded files are scratch and removed individually even on
failure. Whole-game hashes/node proof + safe small delta are the only outputs.
Unity runtime acceptance is explicitly not established by this transform.
"""
import argparse
import json
import importlib.metadata
import inspect
from pathlib import Path
from build_bundle import BASE,canonical,checked,encode_delta,nodes,require,sha

TARGET="9a2cdcaa9ac356fe95df9b5a5ad5df6bba93330ad1591685553031729628d3c4"
REL="Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/charactereditor"
def main(args):
    source=Path(args.original);target=Path(args.target);out=Path(args.output).resolve()
    require(not out.exists(),"Output must not exist")
    checked(source,BASE[REL]);checked(target,TARGET);out.mkdir(parents=True)
    scratch=[out/"original.DO-NOT-DISTRIBUTE.unityfs",out/"target.DO-NOT-DISTRIBUTE.unityfs"]
    try:
        original=canonical(Path(args.patcher),source,scratch[0]);modified=canonical(Path(args.patcher),target,scratch[1])
        source_nodes=nodes(original);target_nodes=nodes(modified)
        require([n["name"]for n in source_nodes]==[n["name"]for n in target_nodes],"Node names/order changed")
        payload,stats=encode_delta(original,modified);(out/"charactereditor.nbd").write_bytes(payload)
        import UnityPy.files.BundleFile as bundle_module
        import UnityPy.helpers.CompressionHelper as compression_module
        proof={"format":"nebula-editor-canonical-construction-v1","original_file_sha256":BASE[REL],"manual_target_sha256":TARGET,"canonical_source_sha256":sha(original),"canonical_target_sha256":sha(modified),"canonical_source_size":len(original),"canonical_target_size":len(modified),"source_nodes":source_nodes,"target_nodes":target_nodes,"delta":stats,"delta_size":len(payload),"decoded_node_bytes_preserved_by_transform":True,"independent_unitypy_node_parity":True,"unitypy_version":importlib.metadata.version("UnityPy"),"unitypy_bundle_source_sha256":sha(Path(inspect.getfile(bundle_module)).read_bytes()),"unitypy_compression_source_sha256":sha(Path(inspect.getfile(compression_module)).read_bytes()),"compression_layout_and_file_hash_changed":True,"unity_runtime_acceptance":False,"installed":False,"game_executed":False,"tests_executed":False}
        (out/"editor-proof.json").write_text(json.dumps(proof,indent=2)+"\n",encoding="utf-8");print(json.dumps(proof))
    finally:
        for path in scratch:
            if path.exists():require(path.is_file()and not path.is_symlink(),"Unexpected scratch path");path.unlink()

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--original",required=True);p.add_argument("--target",required=True);p.add_argument("--patcher",required=True);p.add_argument("--output",required=True);main(p.parse_args())
