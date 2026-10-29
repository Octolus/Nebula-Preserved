"""Read only blend-channel names from the two shipped default head bundles.

No geometry, textures, game process or network is exported/started. Preset bN
maps to zero-based blend index N-1; the native readers append a final zero.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import hashlib
import json
from pathlib import Path

import UnityPy


HEADS = {
    "MALE": {"id": "sL0D2k3asbB756Yb2qJ0LchSiLsKw5Cf", "prefix": "S_0_",
             "sha256": "0db9f6f9bb7875ec8f48f35d157296372ed96e639ead9e948723246f71d26ed3",
             "native_capture_count": 91, "preset_field_count": 92, "shipped_selected_renderer_count": 3},
    "FEMALE": {"id": "fVyLwiL15UE3U70354TJWIXiN8Y8K5C4", "prefix": "S_8_",
               "sha256": "530a90ddaaef12ffb8d67d14b6bbba7f357b79b0ad29070f8a205a59b5f5783b",
               "native_capture_count": 87, "preset_field_count": 88, "shipped_selected_renderer_count": 2},
}


def inspect(root):
    result = {"evidence_type": "static serialized Unity mesh channel names; no runtime validation",
              "target_execution": False, "unitypy_version": UnityPy.__version__, "heads": {}}
    for gender, expected in HEADS.items():
        path = root / "04" / expected["id"].lower()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected["sha256"]:
            raise ValueError("Unsupported head bundle hash: " + str(path))
        env = UnityPy.load(str(path))
        by_id = {obj.path_id: obj for obj in env.objects}
        renderers = []
        for obj in env.objects:
            if obj.type.name != "SkinnedMeshRenderer":
                continue
            data = obj.read()
            name = data.m_GameObject.deref_parse_as_object().m_Name
            if not name.startswith(expected["prefix"] + expected["id"] + "_lod"):
                continue
            tree = obj.read_typetree()
            mesh_ref = tree["m_Mesh"]
            if mesh_ref["m_FileID"] != 0:
                raise ValueError("Unexpected external default-head mesh")
            mesh = by_id[mesh_ref["m_PathID"]].read_typetree()
            channels = mesh["m_Shapes"]["channels"]
            renderers.append({"renderer": name, "renderer_path_id": obj.path_id,
                              "mesh_name": mesh["m_Name"], "mesh_path_id": mesh_ref["m_PathID"],
                              "channels": [{"blend_index": index, "preset_field": "b" + str(index + 1),
                                            "name": channel["name"], "frame_index": channel["frameIndex"],
                                            "frame_count": channel["frameCount"],
                                            "native_reader_captures": index < expected["native_capture_count"]}
                                           for index, channel in enumerate(channels)]})
        if len(renderers) != expected["shipped_selected_renderer_count"]:
            raise ValueError("Unexpected count of native-selected default-head LOD meshes")
        renderers.sort(key=lambda row: row["renderer"])
        names = [[x["name"] for x in row["channels"]] for row in renderers]
        result["heads"][gender] = {**expected, "bundle": str(path), "renderers": renderers,
                                    "all_lod_raw_channel_names_equal": all(x == names[0] for x in names),
                                    "native_reader_final_padding_field": "b" + str(expected["preset_field_count"])}
    result["limitations"] = [
        "Channel names describe the shipped default head meshes, not arbitrary replacement heads.",
        "Native ReadMaleBlends586e30 captures indices0..90 then appends zero b92; female5820f0 captures0..86 then appends zero b88.",
        "The female mesh has88 channels, but native read/save does not capture index87; it emits zero for b88.",
        "Native WriteFemaleBlends also recognizes a lod2 name, but the shipped inspected bundle has matching head renderers only for lod0/lod1.",
        "Raw channel names differ across LODs through mesh-name prefixes; raw-name inequality alone does not imply different semantic index order.",
        "Body height must be traced through CHARACTEREDITOR_SLIDERS.Height and bone fields; b73 is a neck channel.",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=game_path('Nebula Realms_Data/StreamingAssets/StandaloneWindows'))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Refusing to overwrite an existing evidence file")
    data = inspect(args.root)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({gender: {"lod_meshes": len(head["renderers"]),
                                "channels": len(head["renderers"][0]["channels"]),
                                "b73": head["renderers"][0]["channels"][72]["name"],
                                "raw_lod_names_equal": head["all_lod_raw_channel_names_equal"]}
                      for gender, head in data["heads"].items()}))


if __name__ == "__main__":
    main()
