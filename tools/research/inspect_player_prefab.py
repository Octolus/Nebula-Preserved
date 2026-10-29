"""Read-only extraction of the shipped Mirror player component order/state."""

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
from pathlib import Path
import struct

import UnityPy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    path = args.game / "Nebula Realms_Data/StreamingAssets/StandaloneWindows/s/nebulaplayer"
    env = UnityPy.load(str(path))
    root = env.container["assets/resources/nebulaplayer.prefab"]
    tree = root.read_typetree()
    objects = {obj.path_id: obj for obj in env.objects}
    components = []
    for entry in tree["m_Component"]:
        obj = objects[entry["component"]["m_PathID"]]
        data = obj.read_typetree()
        name = obj.type.name
        if name == "MonoBehaviour":
            script = objects[data["m_Script"]["m_PathID"]].read()
            name = ".".join(filter(None, [script.m_Namespace, script.m_ClassName]))
        components.append({"root_component_order": len(components), "path_id": obj.path_id,
                           "type": name, "fields": data})
    identity = next(x for x in components if x["type"] == "Mirror.NetworkIdentity")
    transform = next(x for x in components if x["type"] == "Mirror.NetworkTransform")
    syncvars = next(x for x in components if x["type"].endswith(".NebulaPlayerSyncVars"))
    tf = components[0]["fields"]
    position, rotation = tf["m_LocalPosition"], tf["m_LocalRotation"]
    pos = [position[k] for k in ("x", "y", "z")]
    rot = [rotation[k] for k in ("x", "y", "z", "w")]
    speed = syncvars["fields"]["speed"]
    # Exact component envelopes observed in NetworkIdentity.OnSerializeAllSafely
    # / OnSerializeSafely. Disabled NetworkTransform still has initial state.
    payload = struct.pack("<Bi7fBif", 0, 28, *pos, *rot, 1, 4, speed)
    result = {
        "scope": "Static player prefab and client deserializer constraints; no runtime validation",
        "bundle_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "asset_guid": identity["fields"]["m_AssetId"], "scene_id": identity["fields"]["sceneId"],
        "root_components": components,
        "network_behaviour_order": [
            {"index": 0, "type": transform["type"], "enabled": transform["fields"]["m_Enabled"],
             "initial_state": "Vector3 localPosition (3 float32), Quaternion localRotation (4 float32)",
             "bytes": 28},
            {"index": 1, "type": syncvars["type"], "initial_state": "float32 speed",
             "bytes": 4, "delta": "UInt64 dirty mask, bit0 gates float32 speed"},
        ],
        "envelope": "Each component: uint8 index, int32 little-endian byte count, component bytes",
        "baseline": {"localPosition": position, "localRotation": rotation, "speed": speed},
        "baseline_initial_payload_bytes": len(payload),
        "baseline_initial_payload_hex": payload.hex(),
        "native_rvas": {"component_discovery": "0x1291a50", "component_envelopes": "0x1292700",
                        "component_length": "0x1292930", "transform_initial_read": "0x126cb90",
                        "transform_initial_write": "0x126cf50", "speed_read": "0x614040",
                        "speed_write": "0x614380"},
        "limitations": ["NetworkIdentity.GetComponents<NetworkBehaviour>() uses root component order, not child traversal.",
                        "Spawn ordering, ownership and application handshake must be implemented separately.",
                        "The baseline root transform is asset state, not a verified world spawn point.",
                        "No runtime equivalence or original server spawn policy is claimed."],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"Saved {len(components)} ordered root components; {len(payload)}-byte initial-state baseline")


if __name__ == "__main__":
    main()
